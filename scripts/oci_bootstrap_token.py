"""Mint a temporary OCI session bundle without copying a registered API key."""
import argparse
import base64
import hashlib
import json
import sys
import time
from pathlib import Path

import oci
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from oci_wif import WifError, private_write


def claims(token):
    try:
        part = token.split('.')[1]
        body = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except Exception:
        raise WifError('Session token claims are malformed.') from None


def mint(settings, now, config_loader=oci.config.from_file, client_factory=oci.identity_data_plane.DataplaneClient):
    config = config_loader(profile_name=settings.get('oci_profile', 'HOMEMOVIES_OPERATOR'))
    if config['tenancy'] != settings['tenancy_ocid'] or config['region'] != settings['region']:
        raise WifError('Destination profile and bootstrap settings differ.')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    token = client_factory(config).generate_user_security_token(
        oci.identity_data_plane.models.GenerateUserSecurityTokenDetails(
            public_key=public.decode(), session_expiration_in_minutes=60),
        retry_strategy=oci.retry.NoneRetryStrategy()).data.token
    body = claims(token)
    if (body.get('tenant') != config['tenancy'] or body.get('sub') != config['user']
            or type(body.get('exp')) is not int or not now + 3000 <= body['exp'] <= now + 3660):
        raise WifError('Issued session identity or expiry did not match the destination profile.')
    der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    digest = hashlib.md5(der, usedforsecurity=False).hexdigest()
    return {'token': token, 'expires_at': body['exp'], 'user_ocid': config['user'],
            'tenancy_ocid': config['tenancy'], 'region': config['region'],
            'fingerprint': ':'.join(digest[i:i+2] for i in range(0, len(digest), 2)),
            'private_key': key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()).decode()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        settings = json.loads(Path(args.settings).read_text())
        bundle = mint(settings, int(time.time()))
        private_write(Path(args.output), json.dumps(bundle))
        print('One-hour destination session bundle created with a new ephemeral key; no values printed.')
        return 0
    except Exception:
        print('Session mint failed; raw details suppressed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
