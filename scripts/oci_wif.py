"""GitHub-hosted runner token exchange. Never accepts secrets on the command line."""
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class WifError(Exception):
    """Safe diagnostic: all underlying HTTP/SDK details remain suppressed."""


def require(env, name):
    value = env.get(name, '')
    if not value or any(char in value for char in '\r\n\0'):
        raise WifError('Missing or invalid configuration: ' + name)
    return value


def secure_url(value, expected_host=None):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.fragment or parsed.port not in (None, 443) or
            (expected_host and parsed.hostname != expected_host)):
        raise WifError('Invalid HTTPS endpoint.')
    return parsed


def request_json(session, method, url, **kwargs):
    try:
        response = session.request(method, url, timeout=30, allow_redirects=False, **kwargs)
        if response.status_code != 200:
            raise WifError('Token request failed; HTTP status ' + str(response.status_code))
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except WifError:
        raise
    except Exception:
        raise WifError('Token request failed; raw details suppressed.') from None


def validate_claims(token, env, now):
    # These checks prevent configuration mistakes. OCI verifies the JWT signature.
    try:
        parts = token.split('.')
        if len(parts) != 3:
            raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
        ref = require(env, 'GITHUB_REF')
        if not ref.startswith('refs/heads/') or env.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch'):
            raise ValueError()
        expected = {
            'iss': 'https://token.actions.githubusercontent.com',
            'sub': 'repo:' + require(env, 'GITHUB_REPOSITORY') + ':environment:' + require(env, 'HM_GITHUB_ENVIRONMENT'),
            'repository': require(env, 'GITHUB_REPOSITORY'),
            'repository_id': require(env, 'GITHUB_REPOSITORY_ID'),
            'ref': ref,
        }
        if any(claims.get(key) != value for key, value in expected.items()):
            raise ValueError()
        audience = claims.get('aud')
        if audience != require(env, 'OCI_WIF_AUDIENCE'):
            raise ValueError()
        expiry = claims.get('exp')
        if type(expiry) is not int or expiry < now + 30:
            raise ValueError()
    except Exception:
        raise WifError('GitHub identity claims do not match the deployment boundary.') from None


def exchange(env, session, public_key, now):
    domain = require(env, 'OCI_WIF_DOMAIN_URL')
    parsed_domain = secure_url(domain)
    if parsed_domain.path not in ('', '/') or parsed_domain.query:
        raise WifError('Supply the identity-domain base URL only.')
    oidc_url = require(env, 'ACTIONS_ID_TOKEN_REQUEST_URL')
    parsed = secure_url(oidc_url)
    # GitHub sets this URL. Restrict it to GitHub's hosted Actions service.
    if not parsed.hostname.endswith('.actions.githubusercontent.com'):
        raise WifError('Invalid GitHub Actions token endpoint.')
    query = [(key, val) for key, val in parse_qsl(parsed.query) if key != 'audience']
    query.append(('audience', require(env, 'OCI_WIF_AUDIENCE')))
    oidc_url = urlunsplit(parsed._replace(query=urlencode(query)))
    token = request_json(session, 'GET', oidc_url, headers={
        'Authorization': 'Bearer ' + require(env, 'ACTIONS_ID_TOKEN_REQUEST_TOKEN')}).get('value')
    if not isinstance(token, str):
        raise WifError('GitHub token response was incomplete.')
    validate_claims(token, env, now)
    result = request_json(session, 'POST', domain.rstrip('/') + '/oauth2/v1/token',
                          auth=(require(env, 'OCI_WIF_CLIENT_ID'), require(env, 'OCI_WIF_CLIENT_SECRET')),
                          data={
                              'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
                              'requested_token_type': 'urn:oci:token-type:oci-upst',
                              'subject_token_type': 'jwt', 'subject_token': token,
                              'public_key': public_key,
                          })
    security_token = result.get('token')
    if not isinstance(security_token, str) or not security_token or any(c in security_token for c in '\r\n\0'):
        raise WifError('OCI token response was incomplete.')
    return security_token


def private_write(path, data):
    # Exclusive creation: never overwrite an existing credential/config file.
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data if isinstance(data, bytes) else data.encode())


def install_credentials(directory, config_path, env, private_key, fingerprint, token):
    private_write(directory / 'private.pem', private_key)
    private_write(directory / 'security-token', token)
    lines = ['[HOMEMOVIES]',
             'user=' + require(env, 'OCI_WIF_SERVICE_USER_OCID'),
             'tenancy=' + require(env, 'OCI_TENANCY_OCID'),
             'region=' + require(env, 'OCI_REGION'),
             'fingerprint=' + fingerprint,
             'key_file=' + str(directory / 'private.pem'),
             'security_token_file=' + str(directory / 'security-token')]
    config = '\n'.join(lines) + '\n'
    private_write(directory / 'config', config)
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_write(config_path, config)


def cleanup(directory, config_path, runner_temp):
    directory = Path(directory)
    root = Path(runner_temp).resolve()
    if directory.is_symlink() or directory.resolve().parent != root or not directory.name.startswith('homemovies-wif-'):
        raise WifError('Refusing to clean an unrelated credential directory.')
    expected = directory / 'config'
    if expected.exists() and config_path.exists() and not config_path.is_symlink():
        if expected.read_bytes() == config_path.read_bytes():
            config_path.unlink()
    if directory.exists():
        shutil.rmtree(directory)


def mask(value):
    print('::add-mask::' + value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A'), flush=True)


def hosted_runner(env):
    if env.get('GITHUB_ACTIONS') != 'true' or env.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise WifError('Credential setup is restricted to ephemeral GitHub-hosted runners.')


def setup(env):
    hosted_runner(env)
    for name in ['OCI_WIF_DOMAIN_URL', 'OCI_WIF_CLIENT_ID', 'OCI_WIF_CLIENT_SECRET',
                 'OCI_WIF_SERVICE_USER_OCID', 'OCI_TENANCY_OCID']:
        mask(require(env, name))
    config_path = Path.home() / '.oci' / 'config'
    if config_path.exists() or config_path.is_symlink():
        raise WifError('Refusing to overwrite an existing OCI configuration.')
    runner_temp = require(env, 'RUNNER_TEMP')
    directory = Path(tempfile.mkdtemp(prefix='homemovies-wif-', dir=runner_temp))
    try:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        # OCI requires an MD5 key fingerprint; this is an identifier, not a signature.
        digest = hashlib.md5(public, usedforsecurity=False).hexdigest()
        fingerprint = ':'.join(digest[i:i + 2] for i in range(0, len(digest), 2))
        with requests.Session() as session:
            token = exchange(env, session, base64.b64encode(public).decode(), int(time.time()))
        mask(token)
        install_credentials(directory, config_path, env, private, fingerprint, token)
        import oci
        config = oci.config.from_file(str(config_path), 'HOMEMOVIES')
        signer = oci.auth.signers.SecurityTokenSigner(token, key)
        namespace = oci.object_storage.ObjectStorageClient(config, signer=signer).get_namespace().data
        mask(namespace)
        exports = {'HM_WIF_DIRECTORY': str(directory), 'OCI_CONFIG_FILE': str(config_path),
                   'OCI_CLI_PROFILE': 'HOMEMOVIES', 'OCI_CLI_AUTH': 'security_token',
                   'TF_VAR_oci_auth': 'SecurityToken', 'TF_VAR_config_file_profile': 'HOMEMOVIES'}
        with open(require(env, 'GITHUB_ENV'), 'a') as stream:
            for name, value in exports.items():
                stream.write(name + '=' + value + '\n')
        print('OCI workload identity established; tenancy namespace verified.')
    except Exception:
        cleanup(directory, config_path, runner_temp)
        raise WifError('OCI workload identity setup failed; raw details suppressed.') from None


def main():
    try:
        if sys.argv[1:] == ['cleanup']:
            hosted_runner(os.environ)
            directory = os.environ.get('HM_WIF_DIRECTORY')
            if directory:
                cleanup(Path(directory), Path.home() / '.oci' / 'config', require(os.environ, 'RUNNER_TEMP'))
        elif not sys.argv[1:]:
            setup(os.environ)
        else:
            raise WifError('Unsupported command.')
        return 0
    except Exception:
        print('OCI WIF operation failed; raw details suppressed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
