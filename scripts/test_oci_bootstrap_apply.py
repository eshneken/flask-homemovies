import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oci_bootstrap_apply as apply_module
import oci_bootstrap_plan as bootstrap
from oci_wif import WifError
from test_oci_bootstrap_plan import ENV

APPLY_ENV = dict(ENV, GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                 HM_GITHUB_ENVIRONMENT='homemovies-bootstrap', ENABLE_HOME_MOVIES_BOOTSTRAP_APPLY='true',
                 GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/migration')


class Domain:
    """Fake SCIM server stores writes, including partial writes before failure."""
    def __init__(self):
        self.resources = {'Users': [], 'Groups': [], 'IdentityPropagationTrusts': [
            {'id': 'grocery-trust-id', 'name': 'grocery-existing-trust'}]}
        self.session = Mock()
        self.session.request.side_effect = self.request

    def request(self, method, url, **kwargs):
        if url.endswith('/oauth2/v1/token'):
            return Mock(status_code=200, json=lambda: {'access_token': '<test-only>'})
        kind = url.rsplit('/', 1)[-1]
        if method == 'PATCH':
            trust = next(t for t in self.resources['IdentityPropagationTrusts'] if t['id'] == kind)
            if kwargs['headers']['If-Match'] != trust['meta']['version']:
                return Mock(status_code=412, json=lambda: {})
            for operation in kwargs['json']['Operations']:
                if operation['op'] != 'add' or operation['path'] not in ('oauthClients', 'clientClaimValues', 'impersonationServiceUsers'):
                    raise AssertionError('Only additive trust changes are allowed')
                trust[operation['path']].extend(copy.deepcopy(operation['value']))
            trust['meta']['version'] = '<test-version-2>'
            return Mock(status_code=200, json=lambda: copy.deepcopy(trust))
        if method == 'GET':
            body = {'Resources': copy.deepcopy(self.resources[kind]), 'totalResults': len(self.resources[kind])}
            return Mock(status_code=200, json=lambda: body)
        if method != 'POST':
            raise AssertionError('Updates and deletes are forbidden')
        body = dict(kwargs['json'], id=kind + '-' + str(len(self.resources[kind])))
        self.resources[kind].append(body)
        return Mock(status_code=201, json=lambda: copy.deepcopy(body))


class BootstrapApplyTests(unittest.TestCase):
    def test_create_verify_and_repeat_without_duplicate_writes(self):
        domain = Domain()
        grocery = copy.deepcopy(domain.resources['IdentityPropagationTrusts'][0])
        result = apply_module.apply(APPLY_ENV, domain.session)
        self.assertEqual([result[k] for k in ('service_users_created', 'groups_created', 'trusts_created')], [2, 2, 1])
        self.assertFalse(result['iam_policies_changed'])
        self.assertFalse(result['workload_resources_changed'])
        self.assertEqual(domain.resources['IdentityPropagationTrusts'][0], grocery)
        for user in domain.resources['Users']:
            self.assertTrue(user[bootstrap.USER_EXTENSION]['serviceUser'])
            self.assertNotIn('password', user)
            self.assertNotIn('emails', user)
        for group, user in zip(domain.resources['Groups'], domain.resources['Users']):
            self.assertEqual(group['members'], [{'value': user['id'], 'type': 'User'}])
        domain.session.reset_mock()
        repeat = apply_module.apply(APPLY_ENV, domain.session)
        self.assertEqual([repeat[k] for k in ('service_users_created', 'groups_created', 'trusts_created')], [0, 0, 0])
        self.assertTrue(all(c.args[0] == 'GET' or c.args[1].endswith('/oauth2/v1/token')
                            for c in domain.session.request.call_args_list))
        self.assertNotIn('<test-only>', str(result))
        self.assertNotIn('Users-0', str(result))

    def test_missing_guard_rejects_before_authentication(self):
        cases = {'GITHUB_ACTIONS': 'false', 'RUNNER_ENVIRONMENT': 'self-hosted',
                 'HM_GITHUB_ENVIRONMENT': 'homemovies-production', 'ENABLE_HOME_MOVIES_BOOTSTRAP_APPLY': 'false',
                 'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REF': 'refs/tags/release'}
        for key, value in cases.items():
            with self.subTest(key=key), self.assertRaises(WifError):
                session = Mock()
                apply_module.apply(dict(APPLY_ENV, **{key: value}), session)
            session.request.assert_not_called()

    def test_existing_conflict_is_checked_before_any_resource_write(self):
        for resource in ('Users', 'Groups', 'IdentityPropagationTrusts'):
            domain = Domain()
            domain.resources[resource].append({'userName': bootstrap.USERS[0],
                                              'displayName': bootstrap.GROUPS[0], 'name': bootstrap.TRUST_NAME})
            with self.subTest(resource=resource), self.assertRaises(WifError):
                apply_module.apply(APPLY_ENV, domain.session)
            self.assertEqual(len(domain.session.request.call_args_list), 4)

    def test_shared_issuer_conflict_stops_before_creating_users(self):
        domain = Domain()
        domain.resources['IdentityPropagationTrusts'][0]['issuer'] = 'https://token.actions.githubusercontent.com'
        with self.assertRaisesRegex(WifError, 'GitHub issuer already belongs'):
            apply_module.apply(APPLY_ENV, domain.session)
        self.assertEqual(domain.resources['Users'], [])
        self.assertEqual(domain.resources['Groups'], [])
        self.assertEqual(domain.session.request.call_count, 4)

    def test_partial_success_is_reconciled_without_duplicate_user(self):
        domain = Domain()
        original = domain.request
        def interrupted(method, url, **kwargs):
            response = original(method, url, **kwargs)
            if method == 'POST' and url.endswith('/Users'):
                raise RuntimeError('<test-sensitive-network-error>')
            return response
        domain.session.request.side_effect = interrupted
        with self.assertRaises(WifError):
            apply_module.apply(APPLY_ENV, domain.session)
        self.assertEqual(len(domain.resources['Users']), 1)
        domain.session.request.side_effect = original
        result = apply_module.apply(APPLY_ENV, domain.session)
        self.assertEqual(result['service_users_created'], 1)
        self.assertEqual(len(domain.resources['Users']), 2)

    def test_bad_create_responses_stop_subsequent_writes(self):
        for kind, body, status in (
                ('Users', {'id': 'id', 'userName': bootstrap.USERS[0]}, 201),
                ('Users', {'id': '', 'userName': bootstrap.USERS[0], bootstrap.USER_EXTENSION: {'serviceUser': True}}, 201),
                ('Groups', {'id': 'id', 'displayName': 'wrong-group'}, 201),
                ('Groups', {'id': '', 'displayName': bootstrap.GROUPS[0]}, 201),
                ('Users', {}, 409)):
            domain = Domain()
            original = domain.request
            def bad(method, url, **kwargs):
                if method == 'POST' and url.endswith('/' + kind):
                    return Mock(status_code=status, json=lambda: body)
                return original(method, url, **kwargs)
            domain.session.request.side_effect = bad
            with self.subTest(kind=kind, status=status), self.assertRaises(WifError):
                apply_module.apply(APPLY_ENV, domain.session)
            self.assertEqual(len(domain.resources['IdentityPropagationTrusts']), 1)

    def test_group_membership_conflict_never_changes_existing_group(self):
        domain = Domain()
        apply_module.apply(APPLY_ENV, domain.session)
        for members in ([], [{'value': 'unrelated-user'}], [{'value': 'Users-0', 'type': 'Group'}],
                        [{'value': 'Users-0'}, {'value': 'unrelated-user'}], None):
            domain.resources['Groups'][0]['members'] = members
            with self.subTest(members=members), self.assertRaises(WifError):
                bootstrap.plan(ENV, domain.session)

    def test_incomplete_verification_is_failure(self):
        domain = Domain()
        original = domain.request
        reads = 0
        def incomplete(method, url, **kwargs):
            nonlocal reads
            if method == 'GET' and url.endswith('/IdentityPropagationTrusts'):
                reads += 1
                if reads == 2:
                    return Mock(status_code=200, json=lambda: {'Resources': [], 'totalResults': 0})
            return original(method, url, **kwargs)
        domain.session.request.side_effect = incomplete
        with self.assertRaises(WifError):
            apply_module.apply(APPLY_ENV, domain.session)

    def test_main_sanitizes_outputs_and_failure(self):
        with patch.object(apply_module, 'apply', return_value={'operation': 'identity-create-verified'}), patch('builtins.print') as output:
            self.assertEqual(apply_module.main(), 0)
            self.assertIn('identity-create-verified', output.call_args.args[0])
        with patch.object(apply_module, 'apply', side_effect=RuntimeError('<test-sensitive-error>')), patch('builtins.print') as output:
            self.assertEqual(apply_module.main(), 1)
            self.assertNotIn('<test-sensitive-error>', output.call_args.args[0])
            self.assertIn('Partial creates may exist', output.call_args.args[0])
