import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import oci
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oci_infra_bootstrap as bootstrap
import oci_bootstrap_token as token_module
from oci_wif import WifError

SETTINGS = dict(tenancy_ocid='test-tenancy', compartment_ocid='test-compartment', compartment_name='test-home',
                region='us-ashburn-1', infrastructure_group_ocid='test-infra-group',
                deployment_group_ocid='test-deploy-group', state_bucket_name='test-private-state')


def token(body):
    payload = base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip('=')
    return 'test.' + payload + '.test'


def bundle():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return dict(token=token({'tenant': SETTINGS['tenancy_ocid'], 'sub': 'test-user', 'exp': 4600}),
                expires_at=4600, user_ocid='test-user', tenancy_ocid=SETTINGS['tenancy_ocid'], region=SETTINGS['region'],
                fingerprint='test-fingerprint', private_key=key.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())


class BootstrapTokenTests(unittest.TestCase):
    def test_mint_uses_destination_profile_and_new_key_not_registered_api_key(self):
        loader = Mock(return_value=dict(tenancy=SETTINGS['tenancy_ocid'], region=SETTINGS['region'], user='test-user'))
        client = Mock()
        client.generate_user_security_token.return_value.data.token = token({'tenant': SETTINGS['tenancy_ocid'], 'sub': 'test-user', 'exp': 4600})
        result = token_module.mint(SETTINGS, 1000, loader, Mock(return_value=client))
        loader.assert_called_once_with(profile_name='EDFREETIER')
        details = client.generate_user_security_token.call_args.args[0]
        self.assertEqual(details.session_expiration_in_minutes, 60)
        public = serialization.load_pem_public_key(details.public_key.encode())
        private = serialization.load_pem_private_key(result['private_key'].encode(), password=None)
        self.assertEqual(public.public_numbers(), private.public_key().public_numbers())
        bootstrap.validate_bundle(SETTINGS, result, 1000)

    def test_profile_mismatch_prevents_token_request(self):
        for setting in ('tenancy', 'region'):
            config = dict(tenancy=SETTINGS['tenancy_ocid'], region=SETTINGS['region'], user='test-user')
            config[setting] = 'wrong-destination'
            factory = Mock()
            with self.assertRaises(WifError):
                token_module.mint(SETTINGS, 1000, Mock(return_value=config), factory)
            factory.assert_not_called()

    def test_issued_identity_and_expiration_are_verified(self):
        config = dict(tenancy=SETTINGS['tenancy_ocid'], region=SETTINGS['region'], user='test-user')
        for changed in ({'tenant': 'wrong'}, {'sub': 'wrong'}, {'exp': 1001}, {'exp': 9999}, {'exp': True}):
            body = dict(tenant=config['tenancy'], sub=config['user'], exp=4600, **{})
            body.update(changed)
            client = Mock();client.generate_user_security_token.return_value.data.token = token(body)
            with self.assertRaises(WifError):
                token_module.mint(SETTINGS, 1000, Mock(return_value=config), Mock(return_value=client))

    def test_malformed_claims_and_sanitized_cli(self):
        for value in ('broken', 'one.!invalid.three', token([])):
            with self.assertRaises(WifError): token_module.claims(value)
        with tempfile.TemporaryDirectory() as td:
            settings = Path(td)/'settings.json';settings.write_text(json.dumps(SETTINGS))
            output = Path(td)/'bundle.json'
            args = ['mint', '--settings', str(settings), '--output', str(output)]
            with patch.object(sys, 'argv', args), patch.object(token_module,'mint',return_value={'expires_at':4600}), patch('builtins.print'):
                self.assertEqual(token_module.main(),0)
            self.assertEqual(output.stat().st_mode & 0o777,0o600)
            with patch.object(sys,'argv',args), patch.object(token_module,'mint',side_effect=RuntimeError('<test-sensitive>')), patch('builtins.print') as log:
                self.assertEqual(token_module.main(),1)
                self.assertNotIn('<test-sensitive>',log.call_args.args[0])


class InfraBootstrapTests(unittest.TestCase):
    def test_identity_expiry_and_settings_fail_closed(self):
        good = bundle()
        for changed in ({'region':'wrong'}, {'tenancy_ocid':'wrong'}, {'expires_at':1001},
                        {'token':token({'tenant':'wrong','sub':'test-user','exp':4600})},
                        {'token':token({'tenant':'test-tenancy','sub':'wrong','exp':4600})}):
            with self.assertRaises(WifError): bootstrap.validate_bundle(SETTINGS,dict(good,**changed),1000)
        with self.assertRaises(WifError): bootstrap.validate_bundle(dict(SETTINGS,compartment_name='bad\n'),good,1000)
        with self.assertRaises(WifError): bootstrap.validate_bundle(SETTINGS,good,3000)

    def test_tf_output_private_and_replacements_blocked(self):
        with patch.object(bootstrap.subprocess,'run',return_value=Mock(returncode=1,stdout=b'<test-private>',stderr=b'<test-private>')):
            with self.assertRaisesRegex(WifError,'raw output suppressed'): bootstrap.terraform(Path('test'),['plan'],{})
        with patch.object(bootstrap.subprocess,'run',return_value=Mock(returncode=0,stdout=b'{}')):
            self.assertEqual(bootstrap.terraform(Path('test'),['plan'],{}),b'{}')
        body={'resource_changes':[{'mode':'data','change':{'actions':['read']}},
                                  {'mode':'managed','change':{'actions':['create'],'importing':{'id':'test'}}},
                                  {'mode':'managed','change':{'actions':['update']}}]}
        self.assertEqual(bootstrap.summarize(body),{'creates':1,'updates':1,'deletes':0,'imports':1})
        with self.assertRaises(WifError): bootstrap.summarize({'resource_changes':[{'change':{'actions':['delete','create']}}]})

    def test_bucket_and_metadata_identity_checks(self):
        storage=Mock()
        storage.get_bucket.return_value.data=Mock(compartment_id='test-compartment',public_access_type='NoPublicAccess',versioning='Enabled')
        self.assertTrue(bootstrap.bucket_exists(storage,'test-namespace',SETTINGS))
        storage.get_bucket.return_value.data.public_access_type='ObjectRead'
        with self.assertRaises(WifError): bootstrap.bucket_exists(storage,'test-namespace',SETTINGS)
        for status in (404,403):
            storage.get_bucket.side_effect=oci.exceptions.ServiceError(status,'test-code',{},'<test-only>')
            if status==404: self.assertFalse(bootstrap.bucket_exists(storage,'test-namespace',SETTINGS))
            else:
                with self.assertRaises(WifError): bootstrap.bucket_exists(storage,'test-namespace',SETTINGS)
        storage.get_object.return_value.data.content=json.dumps({'compartment_ocid':'test-compartment'}).encode()
        self.assertEqual(bootstrap.read_metadata(storage,'test-namespace',SETTINGS)['compartment_ocid'],'test-compartment')
        storage.get_object.return_value.data.content=b'{"compartment_ocid":"wrong"}'
        with self.assertRaises(WifError): bootstrap.read_metadata(storage,'test-namespace',SETTINGS)
        for status in (404,403):
            storage.get_object.side_effect=oci.exceptions.ServiceError(status,'test-code',{},'<test-only>')
            if status==404: self.assertEqual(bootstrap.read_metadata(storage,'test-namespace',SETTINGS),{})
            else:
                with self.assertRaises(oci.exceptions.ServiceError): bootstrap.read_metadata(storage,'test-namespace',SETTINGS)

    def test_local_to_remote_backend_does_not_write_credentials_to_backend(self):
        with tempfile.TemporaryDirectory() as td:
            module=Path(td)/'foundation';module.mkdir();(module/'backend.tf').write_text('terraform { backend "oci" {} }')
            bootstrap.local_backend(module)
            self.assertIn('backend "local"',(module/'backend.tf').read_text())
            with patch.object(bootstrap,'terraform'):
                bootstrap.remote_backend(module,SETTINGS,'test-namespace',{})
            config=json.loads((module/'private-backend.json').read_text())
            self.assertEqual(config['auth'],'SecurityToken')
            self.assertNotIn('token',config)
            self.assertEqual((module/'private-backend.json').stat().st_mode & 0o777,0o600)

    def test_full_plan_and_apply_with_durable_state_and_group_handoff(self):
        for operation, exists, resume in (('plan',False,False),('plan',True,True),('apply',False,False),('apply',True,True)):
            with self.subTest(operation=operation,exists=exists), tempfile.TemporaryDirectory() as td:
                root=Path(td)/'repo'
                for name in ('foundation','iam-bootstrap'):
                    module=root/'infra'/name;module.mkdir(parents=True);(module/'versions.tf').write_text('terraform { backend "oci" {} }')
                directory=Path(td)/'homemovies-wif-test';directory.mkdir()
                storage=Mock();storage.get_namespace.return_value.data='test-namespace'
                identity=Mock();identity.get_compartment.return_value.data=SimpleNamespace(name='test-home',lifecycle_state='ACTIVE')
                calls=[]
                def tf(module,args,env):
                    calls.append((module.name,args))
                    if '-target=oci_objectstorage_bucket.state' in args:
                        (module/'terraform.tfstate').write_text('{"version":4}')
                    if args==['show','-json']:
                        return json.dumps({'values':{'root_module':{'resources':[{'address':'oci_identity_dynamic_group.runtime[0]','values':{'id':'test-runtime-group'}}]}}}).encode()
                    if args==['output','-json']:
                        return json.dumps({'runtime_dynamic_group_ocid':{'value':'test-runtime-group'}} if module.name=='iam-bootstrap' else {'vault_ocid':{'value':'test-vault'}}).encode()
                    return b'{}'
                with patch.object(bootstrap.time,'time',return_value=1000),patch.object(bootstrap,'mask'),patch.object(bootstrap.oci.config,'from_file',return_value={}), \
                     patch.object(bootstrap.oci.identity,'IdentityClient',return_value=identity),patch.object(bootstrap.oci.object_storage,'ObjectStorageClient',return_value=storage), \
                     patch.object(bootstrap,'bucket_exists',return_value=exists if operation=='plan' else True) as bucket_check, \
                     patch.object(bootstrap,'read_metadata',return_value={'runtime_dynamic_group_ocid':'test-runtime-group'} if resume else {}), \
                     patch.object(bootstrap,'terraform',side_effect=tf),patch.object(bootstrap,'plan_module',return_value={'creates':1,'updates':0,'deletes':0,'imports':0}):
                    if operation=='apply' and not exists: bucket_check.side_effect=[False,True]
                    result=bootstrap.run(SETTINGS,bundle(),operation,root,directory,Path(td)/'oci'/'config',{})
                self.assertEqual(set(result),{'foundation','iam-bootstrap'})
                if operation=='plan':
                    storage.put_object.assert_not_called()
                    self.assertFalse(any(args[0] in ('apply','state') for _,args in calls))
                else:
                    self.assertTrue(any(args==['state','rm','oci_identity_dynamic_group.runtime[0]'] for _,args in calls))
                    if not exists:
                        state_call=storage.put_object.call_args_list[0]
                        self.assertEqual(state_call.kwargs['if_none_match'],'*')
                        self.assertEqual(state_call.args[2],'foundation/terraform.tfstate')

    def test_main_guards_and_cleanup_on_failure(self):
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'},clear=True),patch('builtins.print'):
            self.assertEqual(bootstrap.main(),1)
        with tempfile.TemporaryDirectory() as td:
            env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',HM_GITHUB_ENVIRONMENT='homemovies-bootstrap',
                     ENABLE_HOME_MOVIES_INFRA_BOOTSTRAP='true',HOME_MOVIES_BOOTSTRAP_OPERATION='plan',GITHUB_REF='refs/heads/test',RUNNER_TEMP=td,
                     OCI_BOOTSTRAP_SETTINGS_JSON=json.dumps(SETTINGS),OCI_IAM_BOOTSTRAP_AUTH_JSON='{}')
            for changed in ({'HM_GITHUB_ENVIRONMENT':'wrong'},{'HOME_MOVIES_BOOTSTRAP_OPERATION':'destroy'},{'GITHUB_REF':'refs/tags/test'}):
                with patch.dict(os.environ,dict(env,**changed),clear=True),patch.object(bootstrap.Path,'home',return_value=Path(td)),patch('builtins.print'):
                    self.assertEqual(bootstrap.main(),1)
            for result in ({'foundation':{'creates':3}},RuntimeError('<test-private>')):
                with patch.dict(os.environ,env,clear=True),patch.object(bootstrap.Path,'home',return_value=Path(td)),patch.object(bootstrap,'run') as run,patch('builtins.print') as log:
                    if isinstance(result,Exception): run.side_effect=result
                    else: run.return_value=result
                    self.assertEqual(bootstrap.main(),1 if isinstance(result,Exception) else 0)
                    self.assertNotIn('<test-private>',log.call_args.args[0])
                self.assertEqual(list(Path(td).glob('homemovies-wif-*')),[])
