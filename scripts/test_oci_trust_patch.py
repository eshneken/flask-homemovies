import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oci_bootstrap_apply as apply_module
import oci_bootstrap_plan as bootstrap
from oci_trust_patch import additions, mappings, verify_preserved
from oci_wif import WifError
from test_oci_bootstrap_apply import APPLY_ENV, Domain

SHARED_ENV = dict(APPLY_ENV, OCI_WIF_SHARED_TRUST_NAME='grocery-existing-trust')


def existing_trust():
    t = bootstrap.desired_trust(SHARED_ENV, {})
    t.update(id='grocery-trust-id', meta={'version': '<test-version-1>'},
             oauthClients=['grocery-client'], clientClaimValues=['grocery-audience'],
             impersonationServiceUsers=[{'rule': 'sub eq repo:example/grocery:environment:production',
                                        'value': 'grocery-user-id', '$ref': 'https://identity.example.com/Users/grocery-user-id',
                                        'ocid': '<test-user-identifier>'}])
    return t


class SharedTrustTests(unittest.TestCase):
    def test_additive_patch_preserves_grocery_and_is_idempotent(self):
        domain = Domain()
        before = existing_trust()
        domain.resources['IdentityPropagationTrusts'] = [copy.deepcopy(before)]
        result = apply_module.apply(SHARED_ENV, domain.session)
        self.assertEqual(result['trusts_created'], 0)
        self.assertEqual(result['existing_trusts_modified_or_deleted'], 1)
        self.assertTrue(result['existing_mappings_preserved'])
        after = domain.resources['IdentityPropagationTrusts'][0]
        verify_preserved(before, after)
        self.assertEqual(after['impersonationServiceUsers'][0], before['impersonationServiceUsers'][0])
        self.assertEqual(len(after['impersonationServiceUsers']), 3)
        patch_calls = [c for c in domain.session.request.call_args_list if c.args[0] == 'PATCH']
        self.assertEqual(len(patch_calls), 1)
        self.assertEqual(patch_calls[0].kwargs['headers']['If-Match'], before['meta']['version'])
        self.assertTrue(all(op['op'] == 'add' for op in patch_calls[0].kwargs['json']['Operations']))
        domain.session.reset_mock()
        repeat = apply_module.apply(SHARED_ENV, domain.session)
        self.assertEqual(repeat['existing_trusts_modified_or_deleted'], 0)
        self.assertFalse(any(c.args[0] == 'PATCH' for c in domain.session.request.call_args_list))

    def test_dedicated_trust_comparison_ignores_server_mapping_metadata(self):
        domain = Domain()
        apply_module.apply(APPLY_ENV, domain.session)
        own = domain.resources['IdentityPropagationTrusts'][-1]
        own['impersonationServiceUsers'][0]['$ref'] = 'https://identity.example.com/Users/test'
        self.assertEqual(bootstrap.plan(APPLY_ENV, domain.session)['trusts_to_create'], 0)

    def test_explicit_shared_trust_must_exist(self):
        domain = Domain()
        domain.resources['IdentityPropagationTrusts'] = []
        with self.assertRaisesRegex(WifError, 'does not exist'):
            apply_module.apply(SHARED_ENV, domain.session)
        self.assertEqual(domain.resources['Users'], [])

    def test_control_or_claim_changes_rejected(self):
        desired = bootstrap.desired_trust(SHARED_ENV, dict(zip(bootstrap.USERS, ['infra-user', 'app-user'])))
        for key, value in (('active', False), ('allowImpersonation', False), ('issuer', 'https://untrusted.example.com'),
                           ('claimValidations', [{'claim': 'sub'}]), ('subjectClaimName', 'email'),
                           ('subjectMappingAttribute', 'userName'), ('oauthClients', []),
                           ('clientClaimValues', [None]), ('meta', {}), ('id', '')):
            with self.subTest(key=key), self.assertRaises(WifError):
                additions(dict(existing_trust(), **{key: value}), desired)

    def test_ambiguous_wildcard_or_conflicting_home_subject_fails(self):
        desired = bootstrap.desired_trust(SHARED_ENV, dict(zip(bootstrap.USERS, ['infra-user', 'app-user'])))
        row = {'rule': desired['impersonationServiceUsers'][0]['rule'], 'value': 'wrong-user'}
        for rows in (None, [{'rule': 'sub eq *', 'value': 'grocery-user'}],
                     [{'rule': 'sub eq repo:example/grocery:*', 'value': 'grocery-user'}],
                     [{'rule': 'email eq example', 'value': 'grocery-user'}],
                     [row, row], [row], [{'rule': 'sub eq repo:example/grocery', 'value': None}]):
            with self.subTest(rows=rows), self.assertRaises(WifError):
                additions(dict(existing_trust(), impersonationServiceUsers=rows), desired)

    def test_concurrent_update_causes_conditional_failure_without_overwriting(self):
        domain = Domain()
        domain.resources['IdentityPropagationTrusts'] = [existing_trust()]
        original = domain.request
        def concurrent(method, url, **kwargs):
            if method == 'PATCH':
                domain.resources['IdentityPropagationTrusts'][0]['meta']['version'] = '<test-concurrent-version>'
            return original(method, url, **kwargs)
        domain.session.request.side_effect = concurrent
        with self.assertRaises(WifError):
            apply_module.apply(SHARED_ENV, domain.session)
        self.assertEqual(len(domain.resources['IdentityPropagationTrusts'][0]['impersonationServiceUsers']), 1)

    def test_verification_rejects_lost_original_controls_clients_audiences_and_rules(self):
        before = existing_trust()
        for key, value in (('active', False), ('oauthClients', []), ('clientClaimValues', []), ('impersonationServiceUsers', [])):
            with self.subTest(key=key), self.assertRaises(WifError):
                verify_preserved(before, dict(before, **{key: value}))
        self.assertEqual(len(mappings(before)), 1)
