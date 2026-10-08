"""Create only the reviewed Home Movies identities; never grant OCI IAM access."""
import json
import os
import sys

import requests

from oci_bootstrap_plan import GROUPS, USERS, USER_EXTENSION, desired_trust, inspect
from oci_trust_patch import additions, verify_preserved
from oci_wif import WifError, request_json


def apply(env, session):
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or env.get('HM_GITHUB_ENVIRONMENT') != 'homemovies-bootstrap'
            or env.get('ENABLE_HOME_MOVIES_BOOTSTRAP_APPLY') != 'true'
            or env.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch')
            or not env.get('GITHUB_REF', '').startswith('refs/heads/')):
        raise WifError('Identity apply requires the protected, opted-in GitHub bootstrap job.')
    base, headers, user_ids, existing_groups, trust_exists, summary = inspect(env, session)
    # Inspect all conflicts before any writes. Never retry a POST automatically:
    # an uncertain response must be reconciled by the next complete inventory.
    for name in USERS:
        if name in user_ids:
            continue
        body = request_json(session, 'POST', base + '/admin/v1/Users',
                            accepted_statuses=(201,), headers=headers,
                            json={'schemas': ['urn:ietf:params:scim:schemas:core:2.0:User'],
                                  'userName': name, 'active': True,
                                  USER_EXTENSION: {'serviceUser': True}})
        if (body.get('userName') != name or not isinstance(body.get('id'), str) or not body['id']
                or body.get(USER_EXTENSION, {}).get('serviceUser') is not True):
            raise WifError('Created service identity could not be verified.')
        user_ids[name] = body['id']
    for name, user in zip(GROUPS, USERS):
        if name in existing_groups:
            continue
        body = request_json(session, 'POST', base + '/admin/v1/Groups',
                            accepted_statuses=(201,), headers=headers,
                            params={'attributes': 'id,displayName,members'},
                            json={'schemas': ['urn:ietf:params:scim:schemas:core:2.0:Group'],
                                  'displayName': name,
                                  'members': [{'value': user_ids[user], 'type': 'User'}]})
        if body.get('displayName') != name or not isinstance(body.get('id'), str) or not body['id']:
            raise WifError('Created group could not be verified.')
    if not trust_exists:
        request_json(session, 'POST', base + '/admin/v1/IdentityPropagationTrusts',
                     accepted_statuses=(201,), headers=headers, json=desired_trust(env, user_ids))
    elif env.get('OCI_WIF_SHARED_TRUST_NAME'):
        changes = additions(trust_exists, desired_trust(env, user_ids))
        if changes:
            request_json(session, 'PATCH', base + '/admin/v1/IdentityPropagationTrusts/' + trust_exists['id'],
                         headers=dict(headers, **{'If-Match': trust_exists['meta']['version']}),
                         json={'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
                               'Operations': changes})
    after = inspect(env, session)
    remaining = after[-1]
    if any(remaining[k] for k in ('service_users_to_create', 'groups_to_create', 'trusts_to_create', 'trusts_to_modify')):
        raise WifError('Post-create inventory is incomplete; review before resuming.')
    if trust_exists and env.get('OCI_WIF_SHARED_TRUST_NAME'):
        verify_preserved(trust_exists, after[4])
    return {
        'operation': 'identity-create-verified',
        'service_users_created': summary['service_users_to_create'],
        'groups_created': summary['groups_to_create'],
        'trusts_created': summary['trusts_to_create'],
        'existing_trusts_modified_or_deleted': summary['trusts_to_modify'],
        'existing_trusts_deleted': 0,
        'existing_mappings_preserved': True,
        'iam_policies_changed': False,
        'workload_resources_changed': False,
    }


def main():
    try:
        with requests.Session() as session:
            result = apply(os.environ, session)
        print(json.dumps(result, indent=2))
        return 0
    except Exception:
        print('Identity apply failed; raw details suppressed. Partial creates may exist; '
              'rerun the read-only plan before resuming.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
