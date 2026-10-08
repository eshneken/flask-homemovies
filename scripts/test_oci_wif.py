import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oci_wif as wif


def environment():
    return {'GITHUB_REPOSITORY': 'example/home-movies', 'GITHUB_REPOSITORY_ID': '1234',
            'HM_GITHUB_ENVIRONMENT': 'test-staging', 'GITHUB_REF': 'refs/heads/migration', 'GITHUB_EVENT_NAME': 'push',
            'OCI_WIF_AUDIENCE': 'example-audience', 'OCI_WIF_DOMAIN_URL': 'https://identity.example.com',
            'OCI_WIF_CLIENT_ID': '<test-only>', 'OCI_WIF_CLIENT_SECRET': '<test-only>',
            'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://pipelines.actions.githubusercontent.com/token?api-version=1',
            'ACTIONS_ID_TOKEN_REQUEST_TOKEN': '<test-only>', 'OCI_WIF_SERVICE_USER_OCID': '<test-user>',
            'OCI_TENANCY_OCID': '<test-tenancy>', 'OCI_REGION': 'us-ashburn-1'}


def jwt(**changes):
    claims = {'iss': 'https://token.actions.githubusercontent.com',
              'sub': 'repo:example/home-movies:environment:test-staging',
              'repository': 'example/home-movies', 'repository_id': '1234',
              'aud': 'example-audience', 'ref': 'refs/heads/migration', 'exp': 2000}
    claims.update(changes)
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return 'header.' + encoded + '.signature'


class WifTests(unittest.TestCase):
    def test_required_values_reject_config_injection(self):
        self.assertEqual(wif.require({'A': 'valid'}, 'A'), 'valid')
        for value in ('', 'bad\nkey_file=other', 'bad\r', 'bad\0'):
            with self.assertRaises(wif.WifError):
                wif.require({'A': value}, 'A')

    def test_https_endpoints_reject_credentials_redirect_hosts_and_ports(self):
        self.assertEqual(wif.secure_url('https://example.com', 'example.com').hostname, 'example.com')
        for url in ('http://example.com', 'https://user:pass@example.com', 'https://example.com#x',
                    'https://example.com:444', 'https://other.com', 'file:///tmp/key'):
            with self.assertRaises(wif.WifError):
                wif.secure_url(url, 'example.com')

    def test_identity_is_bound_to_repository_id_environment_branch_audience_and_expiry(self):
        wif.validate_claims(jwt(), environment(), 1000)
        for claims in ({'iss': 'https://evil.example.com'}, {'sub': 'repo:example/fork:environment:test-staging'},
                       {'repository': 'example/fork'}, {'repository_id': '5678'}, {'ref': 'refs/heads/other'},
                       {'aud': ['example-audience']}, {'exp': 1029}, {'exp': True}):
            with self.subTest(claims=claims), self.assertRaises(wif.WifError):
                wif.validate_claims(jwt(**claims), environment(), 1000)
        for value in ('garbage', 'a.@@.b'):
            with self.assertRaises(wif.WifError):
                wif.validate_claims(value, environment(), 1000)

    def test_all_repository_branches_are_supported_but_prs_and_tags_are_rejected(self):
        for ref in ('refs/heads/main', 'refs/heads/feature/new-player', 'refs/heads/migration'):
            for event in ('push', 'workflow_dispatch'):
                env = dict(environment(), GITHUB_REF=ref, GITHUB_EVENT_NAME=event)
                wif.validate_claims(jwt(ref=ref), env, 1000)
        for ref, event in [('refs/pull/1/merge', 'pull_request'), ('refs/heads/main', 'pull_request_target'),
                           ('refs/tags/v1', 'push')]:
            env = dict(environment(), GITHUB_REF=ref, GITHUB_EVENT_NAME=event)
            with self.assertRaises(wif.WifError):
                wif.validate_claims(jwt(ref=ref), env, 1000)

    def test_exchange_sends_key_bound_native_oci_request_without_redirects(self):
        session = Mock()
        session.request.side_effect = [Mock(status_code=200, json=lambda: {'value': jwt()}),
                                       Mock(status_code=200, json=lambda: {'token': '<test-upst>'})]
        env = environment()
        env['ACTIONS_ID_TOKEN_REQUEST_URL'] += '&audience=wrong'
        self.assertEqual(wif.exchange(env, session, '<public-key>', 1000), '<test-upst>')
        first, second = session.request.call_args_list
        self.assertIn('audience=example-audience', first.args[1])
        self.assertNotIn('audience=wrong', first.args[1])
        self.assertEqual(second.kwargs['data']['public_key'], '<public-key>')
        self.assertEqual(second.kwargs['data']['requested_token_type'], 'urn:oci:token-type:oci-upst')
        self.assertFalse(second.kwargs['allow_redirects'])
        self.assertEqual(second.kwargs['timeout'], 30)

    def test_bad_domain_and_oidc_url_fail_before_secret_request(self):
        for key, value in [('OCI_WIF_DOMAIN_URL', 'https://identity.example.com/extra'),
                           ('ACTIONS_ID_TOKEN_REQUEST_URL', 'https://evil.example.com/token')]:
            env = environment(); env[key] = value
            session = Mock()
            with self.assertRaises(wif.WifError):
                wif.exchange(env, session, '<public-key>', 1000)
            session.request.assert_not_called()

    def test_incomplete_and_injected_token_responses_fail_closed(self):
        for result in ({}, {'value': 1}):
            session = Mock(); session.request.return_value = Mock(status_code=200, json=lambda: result)
            with self.assertRaises(wif.WifError):
                wif.exchange(environment(), session, '<public-key>', 1000)
        for token in (None, '', 123, 'bad\nprofile=x'):
            session = Mock()
            session.request.side_effect = [Mock(status_code=200, json=lambda: {'value': jwt()}),
                                           Mock(status_code=200, json=lambda: {'token': token})]
            with self.assertRaises(wif.WifError):
                wif.exchange(environment(), session, '<public-key>', 1000)

    def test_http_and_json_failures_never_include_server_or_exception_details(self):
        session = Mock()
        cases = [Mock(status_code=403, text='<private-error>'),
                 Mock(status_code=302, text='<private-error>'),
                 Mock(status_code=200, json=lambda: []),
                 Mock(status_code=200, json=Mock(side_effect=ValueError('<private-error>')))]
        for response in cases:
            session.request.return_value = response
            with self.assertRaises(wif.WifError) as caught:
                wif.request_json(session, 'GET', 'https://example.com')
            self.assertNotIn('<private-error>', str(caught.exception))
        session.request.side_effect = RuntimeError('<private-error>')
        with self.assertRaises(wif.WifError) as caught:
            wif.request_json(session, 'GET', 'https://example.com')
        self.assertTrue(caught.exception.__suppress_context__)

    def test_owner_only_credentials_cleanup_and_existing_config_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            directory = Path(tempfile.mkdtemp(prefix='homemovies-wif-', dir=root))
            config = root / 'home' / '.oci' / 'config'
            wif.install_credentials(directory, config, environment(), b'<private-key>', '<fingerprint>', '<test-upst>')
            for path in [config, directory / 'config', directory / 'private.pem', directory / 'security-token']:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn('[HOMEMOVIES]', config.read_text())
            wif.cleanup(directory, config, root)
            self.assertFalse(config.exists()); self.assertFalse(directory.exists())
            directory = Path(tempfile.mkdtemp(prefix='homemovies-wif-', dir=root))
            config.write_text('existing configuration')
            with self.assertRaises(FileExistsError):
                wif.install_credentials(directory, config, environment(), b'<private-key>', '<fingerprint>', '<test-upst>')
            wif.cleanup(directory, config, root)
            self.assertEqual(config.read_text(), 'existing configuration')

    def test_cleanup_rejects_unrelated_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); unrelated = root / 'other'; unrelated.mkdir()
            link = root / 'homemovies-wif-link'; link.symlink_to(unrelated, target_is_directory=True)
            for path in (unrelated, link, root / 'nested' / 'homemovies-wif-other'):
                with self.assertRaises(wif.WifError):
                    wif.cleanup(path, root / 'config', root)
            self.assertTrue(unrelated.exists())
            wif.cleanup(root / 'homemovies-wif-gone', root / 'config', root)

    def test_setup_refuses_local_or_self_hosted_runner_and_existing_user_configuration(self):
        with self.assertRaises(wif.WifError):
            wif.hosted_runner({})
        with self.assertRaises(wif.WifError):
            wif.hosted_runner({'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'self-hosted'})
        env = dict(environment(), GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted')
        with tempfile.TemporaryDirectory() as home:
            config = Path(home) / '.oci' / 'config'; config.parent.mkdir(); config.write_text('preserved')
            with patch.object(Path, 'home', return_value=Path(home)), patch.object(wif, 'mask'), self.assertRaises(wif.WifError):
                wif.setup(env)
            self.assertEqual(config.read_text(), 'preserved')

    def test_full_setup_verifies_namespace_exports_profile_and_cleans_up_on_failure(self):
        import oci
        for should_fail in (False, True):
            with self.subTest(failure=should_fail), tempfile.TemporaryDirectory() as root:
                root = Path(root); home = root / 'home'; home.mkdir(); runner = root / 'runner'; runner.mkdir()
                envfile = root / 'env'; envfile.touch()
                env = dict(environment(), GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                           RUNNER_TEMP=str(runner), GITHUB_ENV=str(envfile))
                with patch.object(Path, 'home', return_value=home), patch.object(wif, 'mask'), \
                        patch.object(wif, 'exchange', return_value='<test-upst>'), \
                        patch('oci.auth.signers.SecurityTokenSigner'), patch('oci.object_storage.ObjectStorageClient') as client:
                    client.return_value.get_namespace.return_value.data = 'test-namespace'
                    if should_fail:
                        client.return_value.get_namespace.side_effect = RuntimeError('<private-error>')
                        with self.assertRaises(wif.WifError) as caught:
                            wif.setup(env)
                        self.assertNotIn('<private-error>', str(caught.exception))
                        self.assertFalse((home / '.oci' / 'config').exists())
                        self.assertEqual(list(runner.iterdir()), [])
                    else:
                        wif.setup(env)
                        exports = dict(line.split('=', 1) for line in envfile.read_text().splitlines())
                        self.assertEqual(exports['TF_VAR_oci_auth'], 'SecurityToken')
                        self.assertEqual(exports['OCI_CLI_PROFILE'], 'HOMEMOVIES')
                        wif.cleanup(Path(exports['HM_WIF_DIRECTORY']), home / '.oci' / 'config', runner)

    def test_mask_escapes_github_command_characters(self):
        with patch('builtins.print') as output:
            wif.mask('a%\r\nb')
        output.assert_called_once_with('::add-mask::a%25%0D%0Ab', flush=True)

    def test_cli_dispatch_and_failures_are_sanitized(self):
        with patch.object(sys, 'argv', ['oci_wif.py']), patch.object(wif, 'setup') as setup:
            self.assertEqual(wif.main(), 0); setup.assert_called_once()
        with patch.object(sys, 'argv', ['oci_wif.py', 'unsupported']), patch('builtins.print') as output:
            self.assertEqual(wif.main(), 1)
            self.assertNotIn('Traceback', str(output.call_args))
        env = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted', 'HM_WIF_DIRECTORY': '<test-dir>', 'RUNNER_TEMP': '<test-root>'}
        with patch.object(sys, 'argv', ['oci_wif.py', 'cleanup']), patch.dict(os.environ, env, clear=True), patch.object(wif, 'cleanup') as cleanup:
            self.assertEqual(wif.main(), 0); cleanup.assert_called_once()
        with patch.object(sys, 'argv', ['oci_wif.py', 'cleanup']), patch.dict(os.environ, {k:v for k,v in env.items() if k!='HM_WIF_DIRECTORY'}, clear=True):
            self.assertEqual(wif.main(), 0)
