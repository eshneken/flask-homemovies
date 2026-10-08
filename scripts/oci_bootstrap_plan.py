"""Read-only plan for dedicated Home Movies service identities and GitHub trust."""
import json
import os
import sys

import requests

from oci_wif import WifError, request_json, require, secure_url
from oci_trust_patch import additions, mappings

USER_EXTENSION = 'urn:ietf:params:scim:schemas:oracle:idcs:extension:user:User'
USERS = ('homemovies-infrastructure', 'homemovies-app-deploy')
GROUPS = ('homemovies-infrastructure', 'homemovies-app-deployers')
TRUST_NAME = 'homemovies-github-actions'


def desired_trust(env, user_ids):
    repository = require(env, 'GITHUB_REPOSITORY')
    client_id = require(env, 'OCI_WIF_CLIENT_ID')
    audience = require(env, 'OCI_WIF_AUDIENCE')
    return {
        'schemas': ['urn:ietf:params:scim:schemas:oracle:idcs:IdentityPropagationTrust'],
        'name': env.get('OCI_WIF_SHARED_TRUST_NAME') or TRUST_NAME, 'type': 'JWT',
        'issuer': 'https://token.actions.githubusercontent.com',
        'publicKeyEndpoint': 'https://token.actions.githubusercontent.com/.well-known/jwks',
        'subjectType': 'User', 'clientClaimName': 'aud', 'clientClaimValues': [audience],
        'oauthClients': [client_id], 'allowImpersonation': True, 'active': True,
        'impersonationServiceUsers': [
            {'rule': 'sub eq repo:' + repository + ':environment:homemovies-infrastructure',
             'value': user_ids.get(USERS[0])},
            {'rule': 'sub eq repo:' + repository + ':environment:homemovies-production',
             'value': user_ids.get(USERS[1])},
        ],
    }


def list_resources(session, base, kind, headers, attributes):
    # Fail if the response is incomplete; never plan creates from a partial listing.
    body = request_json(session, 'GET', base + '/admin/v1/' + kind,
                        headers=headers, params={'count': 1000, 'attributes': attributes})
    resources = body.get('Resources')
    total = body.get('totalResults')
    if not isinstance(resources, list) or type(total) is not int or total != len(resources):
        raise WifError('Identity inventory is incomplete; no changes planned.')
    return resources


def inspect(env, session):
    base = require(env, 'OCI_WIF_DOMAIN_URL').rstrip('/')
    parsed = secure_url(base)
    if parsed.path or parsed.query:
        raise WifError('Supply only the identity-domain base URL.')
    result = request_json(session, 'POST', base + '/oauth2/v1/token',
                          auth=(require(env, 'OCI_BOOTSTRAP_CLIENT_ID'), require(env, 'OCI_BOOTSTRAP_CLIENT_SECRET')),
                          data={'grant_type': 'client_credentials', 'scope': 'urn:opc:idm:__myscopes__'})
    token = result.get('access_token')
    if not isinstance(token, str) or not token or any(c in token for c in '\r\n\0'):
        raise WifError('Administrator token response was incomplete.')
    headers = {'Authorization': 'Bearer ' + token}
    users = list_resources(session, base, 'Users', headers, 'id,userName,' + USER_EXTENSION)
    groups = list_resources(session, base, 'Groups', headers, 'id,displayName,members')
    trusts = list_resources(session, base, 'IdentityPropagationTrusts', headers,
                            'id,name,type,issuer,publicKeyEndpoint,subjectType,clientClaimName,clientClaimValues,oauthClients,allowImpersonation,active,impersonationServiceUsers,meta,claimValidations,subjectClaimName,subjectMappingAttribute')
    # OCI enforces issuer uniqueness within a domain, even when the audience
    # and OAuth client differ. Detect this before creating any identities.
    if any(t.get('issuer') == 'https://token.actions.githubusercontent.com'
           and t.get('name') != (env.get('OCI_WIF_SHARED_TRUST_NAME') or TRUST_NAME) for t in trusts):
        raise WifError('GitHub issuer already belongs to another trust in this domain; '
                       'a separate domain or an explicitly reviewed shared trust is required.')
    user_ids = {}
    for name in USERS:
        matches = [u for u in users if u.get('userName') == name]
        if len(matches) > 1 or (matches and (matches[0].get(USER_EXTENSION, {}).get('serviceUser') is not True or not matches[0].get('id'))):
            raise WifError('A dedicated service-user name conflicts with an existing identity.')
        if matches:
            user_ids[name] = matches[0]['id']
    existing_groups = set()
    for name in GROUPS:
        matches = [g for g in groups if g.get('displayName') == name]
        if len(matches) > 1 or (matches and not matches[0].get('id')):
            raise WifError('A dedicated group name conflicts with existing identities.')
        if matches:
            expected = user_ids.get(USERS[GROUPS.index(name)])
            members = matches[0].get('members', [])
            if not expected or not isinstance(members, list) or len(members) != 1 or members[0].get('value') != expected or members[0].get('type', 'User') != 'User':
                raise WifError('Existing dedicated group membership differs; review required.')
            existing_groups.add(name)
    desired = desired_trust(env, user_ids)
    matches = [t for t in trusts if t.get('name') == desired['name']]
    if len(matches) > 1:
        raise WifError('Dedicated trust name is ambiguous.')
    shared = bool(env.get('OCI_WIF_SHARED_TRUST_NAME'))
    if shared and not matches:
        raise WifError('The explicitly selected shared trust does not exist.')
    changes = []
    if matches:
        if shared:
            changes = additions(matches[0], desired)
        elif (any(matches[0].get(k) != v for k, v in desired.items()
                  if k not in ('schemas', 'impersonationServiceUsers'))
              or mappings(matches[0]) != mappings(desired)):
            raise WifError('Existing Home Movies trust differs; review required before replacement.')
    summary = {
        'service_users_to_create': len(USERS) - len(user_ids),
        'groups_to_create': len(GROUPS) - len(existing_groups),
        'trusts_to_create': 0 if matches else 1,
        'trusts_to_modify_or_delete': int(bool(changes)),
        'trusts_to_modify': int(bool(changes)),
        'trusts_to_delete': 0,
        'iam_policies_changed': False,
        'workload_resources_changed': False,
        'operation': 'read-only-plan',
    }
    return base, headers, user_ids, existing_groups, matches[0] if matches else None, summary


def plan(env, session):
    return inspect(env, session)[-1]


def main():
    try:
        with requests.Session() as session:
            result = plan(os.environ, session)
        print(json.dumps(result, indent=2))
        return 0
    except Exception:
        print('Federation bootstrap plan failed; raw details suppressed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
