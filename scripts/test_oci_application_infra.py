import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oci_application_infra as infrastructure
from oci_wif import WifError

ENV = dict(OCI_DEPLOYMENT_GROUP_OCID='test-deploy-group', OCI_TENANCY_OCID='test-tenancy', OCI_COMPARTMENT_OCID='test-compartment',
           OCI_COMPARTMENT_NAME='test-home', OCI_REGION='us-ashburn-1',
           OCI_AVAILABILITY_DOMAIN='test-ad', OCI_IMAGE_OCID='test-image',
           APP_HOSTNAME='movies.example.com', ACME_EMAIL='admin@example.com',
           OCI_BASTION_CLIENT_CIDR='192.0.2.1/32', OCI_STATE_BUCKET_NAME='test-state',
           GITHUB_REPOSITORY='example/home-movies')
METADATA = dict(vault_ocid='test-vault', vault_key_ocid='test-key', runtime_dynamic_group_ocid='test-group')


class ApplicationInfrastructureTests(unittest.TestCase):
    def test_client_reads_ephemeral_profile(self):
        with tempfile.TemporaryDirectory() as root:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            key_file, token_file = Path(root) / 'key', Path(root) / 'token'
            key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            token_file.write_text('test-token')
            config = dict(key_file=str(key_file), security_token_file=str(token_file))
            with patch.object(infrastructure.oci.config, 'from_file', return_value=config), patch.object(infrastructure.oci.auth.signers, 'SecurityTokenSigner') as signer:
                self.assertEqual(infrastructure.client({'OCI_CONFIG_FILE': str(Path(root) / 'config')})[0], config)
                self.assertEqual(signer.call_args.args[0], 'test-token')

    def test_plan_is_read_only_and_apply_uses_saved_plan_and_private_outputs(self):
        for operation in ('plan', 'apply'):
            with tempfile.TemporaryDirectory() as temporary:
                root, work = Path(temporary) / 'source', Path(temporary) / 'work'
                module = root / 'infra' / 'application'
                module.mkdir(parents=True); work.mkdir(); (root / 'scripts').mkdir()
                (module / 'main.tf').write_text('test'); (root / 'scripts' / 'vm_deploy.py').write_text('test')
                identity, storage = Mock(), Mock()
                identity.get_compartment.return_value.data = NS(name='test-home', lifecycle_state='ACTIVE')
                storage.get_namespace.return_value.data = 'test-namespace'
                calls = []
                def terraform(module, args, env):
                    calls.append((module, args, env))
                    if args[:2] == ['show', '-json']:
                        return json.dumps({'resource_changes': [{'mode': 'managed', 'change': {'actions': ['create']}}]}).encode()
                    if args == ['output', '-json']:
                        return json.dumps({'instance_ocid': {'value': 'test-instance'}, 'runtime_secret_ocid': {'value': 'test-secret'}}).encode()
                    return b''
                with patch.object(infrastructure, 'mask'), patch.object(infrastructure, 'client', return_value=({}, Mock())), \
                        patch.object(infrastructure.oci.identity, 'IdentityClient', return_value=identity), \
                        patch.object(infrastructure.oci.object_storage, 'ObjectStorageClient', return_value=storage), \
                        patch.object(infrastructure, 'bucket_exists', return_value=True), \
                        patch.object(infrastructure, 'read_metadata', return_value=METADATA), \
                        patch.object(infrastructure, 'terraform', side_effect=terraform):
                    self.assertEqual(infrastructure.run(ENV, root, work, operation)['creates'], 1)
                self.assertTrue((work / 'scripts' / 'vm_deploy.py').exists())
                backend = json.loads((work / 'backend.json').read_text())
                self.assertEqual(backend['key'], 'application/terraform.tfstate')
                self.assertEqual(backend['auth'], 'SecurityToken')
                self.assertEqual((work / 'backend.json').stat().st_mode & 0o777, 0o600)
                self.assertEqual(calls[0][2]['TF_VAR_runtime_dynamic_group_ocid'], 'test-group')
                self.assertNotIn('TF_VAR_PASSWORD_HASH', calls[0][2])
                if operation == 'plan':
                    storage.put_object.assert_not_called()
                    self.assertFalse(any(args[0] == 'apply' for _, args, _ in calls))
                else:
                    self.assertTrue(any(args == ['apply', '-input=false', '-no-color', 'review.tfplan'] for _, args, _ in calls))
                    saved = storage.put_object.call_args
                    self.assertEqual(saved.args[2], 'application/outputs.json')
                    self.assertEqual(json.loads(saved.args[3])['compartment_ocid'], 'test-compartment')

    def test_destination_and_foundation_mismatches_prevent_terraform(self):
        for failure in ('name', 'bucket', 'metadata'):
            identity, storage = Mock(), Mock()
            identity.get_compartment.return_value.data = NS(name='other' if failure == 'name' else 'test-home', lifecycle_state='ACTIVE')
            storage.get_namespace.return_value.data = 'test-namespace'
            with patch.object(infrastructure, 'mask'), patch.object(infrastructure, 'client', return_value=({}, Mock())), \
                    patch.object(infrastructure.oci.identity, 'IdentityClient', return_value=identity), \
                    patch.object(infrastructure.oci.object_storage, 'ObjectStorageClient', return_value=storage), \
                    patch.object(infrastructure, 'bucket_exists', return_value=failure != 'bucket'), \
                    patch.object(infrastructure, 'read_metadata', return_value={} if failure == 'metadata' else METADATA), \
                    patch.object(infrastructure, 'terraform') as terraform, self.assertRaises(WifError):
                infrastructure.run(ENV, Path('/test'), Path('/test'), 'plan')
            terraform.assert_not_called()

    def test_main_guards_cleanup_and_sanitized_failure(self):
        with tempfile.TemporaryDirectory() as root:
            env = dict(ENV, RUNNER_TEMP=root, GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                       HM_GITHUB_ENVIRONMENT='homemovies-infrastructure', ENABLE_HOME_MOVIES_APPLICATION_INFRA='true',
                       HOME_MOVIES_APPLICATION_OPERATION='plan', GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/test')
            for change in ({'HM_GITHUB_ENVIRONMENT': 'wrong'}, {'GITHUB_EVENT_NAME': 'pull_request'}, {'HOME_MOVIES_APPLICATION_OPERATION': 'destroy'}):
                with patch.dict(os.environ, dict(env, **change), clear=True), patch('builtins.print'), patch.object(infrastructure, 'run') as run:
                    self.assertEqual(infrastructure.main(), 1); run.assert_not_called()
            for failed in (False, True):
                with patch.dict(os.environ, env, clear=True), patch.object(infrastructure, 'run') as run, patch('builtins.print') as log:
                    run.return_value = {'creates': 1}
                    if failed: run.side_effect = RuntimeError('<private-output>')
                    self.assertEqual(infrastructure.main(), 1 if failed else 0)
                    self.assertNotIn('<private-output>', log.call_args.args[0])
                self.assertEqual(list(Path(root).iterdir()), [])
