import base64
import json
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python_app'))
import app as runtime


class RuntimeFactoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = Path(self.directory.name) / 'runtime.json'
        self.settings = {'B2_APPLICATION_KEY_ID': '<synthetic-key-id>',
                         'B2_APPLICATION_KEY': '<synthetic-key>', 'B2_BUCKET_ID': '<synthetic-bucket>'}
        self.config.write_text(json.dumps(self.settings))
        self.config.chmod(0o600)

    def tearDown(self):
        self.directory.cleanup()

    def test_owner_only_local_settings_bootstrap_native_sdk_and_repository(self):
        with patch.dict(os.environ, {'HM_CONFIG_FILE': str(self.config)}, clear=True), \
                patch.object(runtime, 'B2Api') as api, \
                patch.object(runtime, 'B2Repository') as repository, \
                patch.object(runtime, 'create_app') as create:
            self.assertIs(runtime.create_runtime_app(), create.return_value)
            api.return_value.authorize_account.assert_called_once_with('<synthetic-key-id>', '<synthetic-key>')
            repository.assert_called_once_with(api.return_value, '<synthetic-bucket>', discovery_prefix='')
            create.assert_called_once_with(self.settings, repository.return_value)

    def test_local_file_permissions_and_bad_json_fail_without_disclosing_contents(self):
        for mode, text in ((0o644, json.dumps(self.settings)), (0o600, 'not JSON')):
            self.config.write_text(text)
            self.config.chmod(mode)
            with patch.dict(os.environ, {'HM_CONFIG_FILE': str(self.config)}, clear=True), \
                    patch.object(runtime, 'B2Api') as api:
                with self.assertRaises(RuntimeError) as caught:
                    runtime.create_runtime_app()
                self.assertNotIn('<synthetic-key>', str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)
                api.assert_not_called()

    def test_named_vault_secret_uses_instance_principal_without_secret_listing(self):
        encoded = base64.b64encode(json.dumps(self.settings).encode()).decode()
        bundle = SimpleNamespace(data=SimpleNamespace(secret_bundle_content=SimpleNamespace(content=encoded)))
        with patch.dict(os.environ, {'HM_CONFIG_SECRET_OCID': '<synthetic-secret-id>'}, clear=True), \
                patch('oci.auth.signers.InstancePrincipalsSecurityTokenSigner') as signer, \
                patch('oci.secrets.SecretsClient') as client, \
                patch.object(runtime, 'B2Api'), patch.object(runtime, 'B2Repository'), \
                patch.object(runtime, 'create_app') as create:
            signer.return_value.region = 'example-region'
            client.return_value.get_secret_bundle.return_value = bundle
            self.assertIs(runtime.create_runtime_app(), create.return_value)
            client.assert_called_once_with({'region': 'example-region'}, signer=signer.return_value)
            client.return_value.get_secret_bundle.assert_called_once_with('<synthetic-secret-id>')
            self.assertEqual(create.call_args.args[0], self.settings)

    def test_sdk_failure_is_sanitized(self):
        with patch.dict(os.environ, {'HM_CONFIG_FILE': str(self.config)}, clear=True), \
                patch.object(runtime, 'B2Api') as api:
            api.return_value.authorize_account.side_effect = RuntimeError('<synthetic-sensitive-error>')
            with self.assertRaises(RuntimeError) as caught:
                runtime.create_runtime_app()
            self.assertNotIn('synthetic-sensitive-error', str(caught.exception))

    def test_direct_launcher_binds_only_loopback_and_disables_debug(self):
        with patch.dict(os.environ, {'HM_CONFIG_FILE': str(self.config)}, clear=True), \
                patch('b2sdk.v3.B2Api'), patch('b2_repository.B2Repository'), \
                patch('service.create_app') as create:
            runpy.run_path(str(Path(runtime.__file__)), run_name='__main__')
            create.return_value.run.assert_called_once_with(host='127.0.0.1', port=5055, debug=False)
