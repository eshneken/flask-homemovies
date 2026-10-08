"""Plan additive changes to a reviewed shared GitHub issuer trust."""
from oci_wif import WifError

CONTROLS = ('name', 'type', 'issuer', 'publicKeyEndpoint', 'subjectType',
            'clientClaimName', 'allowImpersonation', 'active')


def mappings(trust):
    rows = trust.get('impersonationServiceUsers', [])
    if not isinstance(rows, list):
        raise WifError('Shared trust mappings are malformed.')
    result = {}
    for row in rows:
        rule, value = row.get('rule'), row.get('value')
        if (not isinstance(rule, str) or not rule.startswith('sub eq repo:')
                or any(c in rule for c in '*\r\n') or rule in result
                or not isinstance(value, str) or not value):
            raise WifError('Shared trust must contain unambiguous exact repository subjects.')
        result[rule] = value
    return result


def additions(existing, desired):
    if any(existing.get(k) != desired[k] for k in CONTROLS):
        raise WifError('Shared trust verification controls differ; no automatic changes allowed.')
    if (existing.get('claimValidations') or existing.get('subjectMappingAttribute')
            or existing.get('subjectClaimName') not in (None, '', 'sub')):
        raise WifError('Shared trust has additional claim constraints requiring review.')
    changes = []
    for key in ('clientClaimValues', 'oauthClients'):
        current = existing.get(key)
        if not isinstance(current, list) or not current or any(not isinstance(v, str) or not v for v in current):
            raise WifError('Shared trust client or audience inventory is incomplete.')
        missing = [v for v in desired[key] if v not in current]
        if missing:
            changes.append({'op': 'add', 'path': key, 'value': missing})
    current = mappings(existing)
    missing = []
    for row in desired['impersonationServiceUsers']:
        if row['rule'] in current:
            if current[row['rule']] != row['value']:
                raise WifError('Home Movies subject already maps to a different identity.')
        else:
            missing.append(row)
    if missing:
        changes.append({'op': 'add', 'path': 'impersonationServiceUsers', 'value': missing})
    if changes and (not isinstance(existing.get('id'), str) or not existing['id']
                    or not isinstance(existing.get('meta', {}).get('version'), str)
                    or not existing['meta']['version']):
        raise WifError('Shared trust requires an identity and conditional version for updates.')
    return changes


def verify_preserved(before, after):
    if any(before.get(k) != after.get(k) for k in CONTROLS + ('id',)):
        raise WifError('Existing shared trust controls were not preserved.')
    for key in ('clientClaimValues', 'oauthClients'):
        if not set(before[key]).issubset(after[key]):
            raise WifError('Existing shared trust client or audience was not preserved.')
    after_rules = mappings(after)
    if any(after_rules.get(rule) != value for rule, value in mappings(before).items()):
        raise WifError('Existing shared trust subject mapping was not preserved.')
