import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oci_bootstrap_plan as bootstrap
from oci_wif import WifError

ENV = {'OCI_WIF_DOMAIN_URL': 'https://identity.example.com', 'OCI_BOOTSTRAP_CLIENT_ID': '<test-admin>',
       'OCI_BOOTSTRAP_CLIENT_SECRET': '<test-only>', 'OCI_WIF_CLIENT_ID': '<test-client>',
       'OCI_WIF_AUDIENCE': 'example-audience', 'GITHUB_REPOSITORY': 'example/home-movies'}


def session_for(users=None, groups=None, trusts=None):
    session = Mock()
    bodies = [{'access_token': '<test-only>'}]
    for resources in (users or [], groups or [], trusts or []):
        bodies.append({'Resources': resources, 'totalResults': len(resources)})
    session.request.side_effect = [Mock(status_code=200, json=lambda b=b: b) for b in bodies]
    return session


class BootstrapPlanTests(unittest.TestCase):
    def test_empty_destination_plans_only_project_identities_and_no_write_requests(self):
        session = session_for(trusts=[{'name': 'grocery-existing-trust'}])
        result = bootstrap.plan(ENV, session)
        self.assertEqual(result['service_users_to_create'], 2)
        self.assertEqual(result['groups_to_create'], 2)
        self.assertEqual(result['trusts_to_create'], 1)
        self.assertFalse(result['iam_policies_changed'])
        self.assertEqual([c.args[0] for c in session.request.call_args_list], ['POST', 'GET', 'GET', 'GET'])
        self.assertTrue(session.request.call_args_list[0].args[1].endswith('/oauth2/v1/token'))
        self.assertNotIn('<test-only>', str(result))

    def test_existing_matching_identities_produce_no_create_plan(self):
        users = [{'userName': n, 'id': n + '-id', bootstrap.USER_EXTENSION: {'serviceUser': True}} for n in bootstrap.USERS]
        groups = [{'displayName': n, 'id': n + '-id', 'members': [{'value': u + '-id', 'type': 'User'}]} for n, u in zip(bootstrap.GROUPS, bootstrap.USERS)]
        trust = bootstrap.desired_trust(ENV, {u['userName']: u['id'] for u in users})
        result = bootstrap.plan(ENV, session_for(users, groups, [trust]))
        self.assertEqual([result[k] for k in ['service_users_to_create','groups_to_create','trusts_to_create']], [0,0,0])
        self.assertIn('environment:homemovies-production', trust['impersonationServiceUsers'][1]['rule'])
        self.assertIn('environment:homemovies-infrastructure', trust['impersonationServiceUsers'][0]['rule'])

    def test_conflicting_user_group_or_trust_is_never_replaced(self):
        user = {'userName': bootstrap.USERS[0], 'id': '<test-id>', bootstrap.USER_EXTENSION: {'serviceUser': True}}
        group = {'displayName': bootstrap.GROUPS[0], 'id': '<test-id>'}
        cases = [([dict(user, **{bootstrap.USER_EXTENSION: {'serviceUser': False}})], [], []),
                 ([user,user], [], []), ([], [group,group], []),
                 ([], [{'displayName': bootstrap.GROUPS[0]}], []),
                 ([], [], [{'name':bootstrap.TRUST_NAME}]),
                 ([], [], [{'name':bootstrap.TRUST_NAME},{'name':bootstrap.TRUST_NAME}])]
        for users, groups, trusts in cases:
            with self.subTest(users=bool(users),groups=bool(groups),trusts=bool(trusts)), self.assertRaises(WifError):
                bootstrap.plan(ENV, session_for(users,groups,trusts))

    def test_partial_or_malformed_inventory_fails_closed(self):
        for body in ({'Resources': [],'totalResults': 5}, {'Resources': None,'totalResults':0}, {'Resources': [],'totalResults':True}):
            session = Mock();session.request.return_value = Mock(status_code=200,json=lambda b=body:b)
            with self.assertRaises(WifError):
                bootstrap.list_resources(session,'https://example.com','Users',{},'id')

    def test_invalid_domain_or_admin_token_fails_before_inventory(self):
        with self.assertRaises(WifError):
            bootstrap.plan(dict(ENV,OCI_WIF_DOMAIN_URL='https://example.com/path'),Mock())
        for token in (None,'',123,'bad\n'):
            session = Mock();session.request.return_value = Mock(status_code=200,json=lambda t=token:{'access_token':t})
            with self.assertRaises(WifError):
                bootstrap.plan(ENV,session)
            self.assertEqual(session.request.call_count,1)

    def test_main_outputs_only_safe_plan_and_sanitizes_failure(self):
        with patch.object(bootstrap,'plan',return_value={'operation':'read-only-plan'}), patch('builtins.print') as output:
            self.assertEqual(bootstrap.main(),0)
            self.assertIn('read-only-plan',output.call_args.args[0])
        with patch.object(bootstrap,'plan',side_effect=RuntimeError('<test-sensitive-error>')), patch('builtins.print') as output:
            self.assertEqual(bootstrap.main(),1)
            self.assertNotIn('<test-sensitive-error>',output.call_args.args[0])
