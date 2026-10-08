"""Gated initial IAM/foundation Terraform bootstrap using ephemeral credentials."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import oci
from cryptography.hazmat.primitives import serialization

from oci_bootstrap_token import claims
from oci_wif import WifError, cleanup, hosted_runner, install_credentials, mask, private_write

REQUIRED = ('tenancy_ocid', 'compartment_ocid', 'compartment_name', 'region',
            'infrastructure_group_ocid', 'deployment_group_ocid', 'state_bucket_name')
STATE_KEYS = {'foundation': 'foundation/terraform.tfstate', 'iam-bootstrap': 'iam-bootstrap/terraform.tfstate'}
METADATA_KEY = 'bootstrap/outputs.json'


def validate_bundle(settings, bundle, now):
    if any(not isinstance(settings.get(k), str) or not settings[k] or any(c in settings[k] for c in '\r\n\0') for k in REQUIRED):
        raise WifError('Bootstrap settings are incomplete.')
    token = bundle.get('token')
    body = claims(token)
    if (body.get('tenant') != settings['tenancy_ocid'] or body.get('sub') != bundle.get('user_ocid')
            or bundle.get('tenancy_ocid') != settings['tenancy_ocid'] or bundle.get('region') != settings['region']
            or type(body.get('exp')) is not int or body['exp'] != bundle.get('expires_at')
            or not now + 2100 <= body['exp'] <= now + 3660):
        raise WifError('Session is expired, too short-lived or belongs to another destination.')
    serialization.load_pem_private_key(bundle['private_key'].encode(), password=None)


def terraform(module, args, env):
    # Never stream Terraform's raw output, which can include IDs/state/hostnames.
    result = subprocess.run(['terraform', '-chdir=' + str(module), *args], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    if result.returncode:
        raise WifError('Terraform command failed; raw output suppressed.')
    return result.stdout


def summarize(body):
    result = {'creates': 0, 'updates': 0, 'deletes': 0, 'imports': 0}
    for resource in body.get('resource_changes', []):
        if resource.get('mode') == 'data':
            continue
        actions = resource['change']['actions']
        for action, key in (('create', 'creates'), ('update', 'updates'), ('delete', 'deletes')):
            result[key] += action in actions
        result['imports'] += bool(resource['change'].get('importing'))
    if result['deletes']:
        raise WifError('Bootstrap would delete or replace a resource; review required.')
    return result


def plan_module(module, env):
    terraform(module, ['plan', '-input=false', '-no-color', '-out=review.tfplan'], env)
    return summarize(json.loads(terraform(module, ['show', '-json', 'review.tfplan'], env)))


def local_backend(module):
    for path in module.glob('*.tf'):
        text = path.read_text()
        if 'backend "oci" {}' in text:
            path.write_text(text.replace('backend "oci" {}', 'backend "local" {}'))


def remote_backend(module, settings, namespace, env):
    for path in module.glob('*.tf'):
        text = path.read_text()
        if 'backend "local" {}' in text:
            path.write_text(text.replace('backend "local" {}', 'backend "oci" {}'))
    backend = module / 'private-backend.json'
    private_write(backend, json.dumps({'bucket': settings['state_bucket_name'], 'namespace': namespace,
                                      'key': STATE_KEYS[module.name], 'region': settings['region'],
                                      'auth': 'SecurityToken', 'config_file_profile': 'HOMEMOVIES'}))
    terraform(module, ['init', '-reconfigure', '-input=false', '-lockfile=readonly', '-backend-config=' + str(backend)], env)


def bucket_exists(storage, namespace, settings):
    try:
        bucket = storage.get_bucket(namespace, settings['state_bucket_name']).data
        if (bucket.compartment_id != settings['compartment_ocid'] or bucket.public_access_type != 'NoPublicAccess'
                or bucket.versioning != 'Enabled'):
            raise WifError('State bucket identity or privacy does not match the reviewed destination.')
        return True
    except oci.exceptions.ServiceError as error:
        if error.status != 404:
            raise WifError('State bucket preflight failed; raw details suppressed.') from None
        return False


def read_metadata(storage, namespace, settings):
    try:
        response = storage.get_object(namespace, settings['state_bucket_name'], METADATA_KEY)
        body = json.loads(response.data.content)
        if body.get('compartment_ocid') != settings['compartment_ocid']:
            raise WifError('Bootstrap output metadata belongs to a different compartment.')
        return body
    except oci.exceptions.ServiceError as error:
        if error.status != 404:
            raise
        return {}


def run(settings, bundle, operation, root, directory, config_path, env):
    validate_bundle(settings, bundle, int(time.time()))
    for value in [*settings.values(), *bundle.values()]:
        if isinstance(value, str):
            mask(value)
    install_credentials(directory, config_path,
                        {'OCI_WIF_SERVICE_USER_OCID': bundle['user_ocid'], 'OCI_TENANCY_OCID': settings['tenancy_ocid'],
                         'OCI_REGION': settings['region']}, bundle['private_key'], bundle['fingerprint'], bundle['token'])
    config = oci.config.from_file(str(config_path), 'HOMEMOVIES')
    key = serialization.load_pem_private_key(bundle['private_key'].encode(), password=None)
    signer = oci.auth.signers.SecurityTokenSigner(bundle['token'], key)
    identity = oci.identity.IdentityClient(config, signer=signer)
    compartment = identity.get_compartment(settings['compartment_ocid']).data
    if compartment.name != settings['compartment_name'] or compartment.lifecycle_state != 'ACTIVE':
        raise WifError('Destination compartment does not match the reviewed name or is inactive.')
    storage = oci.object_storage.ObjectStorageClient(config, signer=signer)
    namespace = storage.get_namespace().data
    mask(namespace)
    exists = bucket_exists(storage, namespace, settings)
    metadata = read_metadata(storage, namespace, settings) if exists else {}
    tf_env = dict(env, OCI_CONFIG_FILE=str(config_path), OCI_CLI_PROFILE='HOMEMOVIES', OCI_CLI_AUTH='security_token',
                  TF_VAR_oci_auth='SecurityToken', TF_VAR_config_file_profile='HOMEMOVIES', TF_IN_AUTOMATION='true')
    for key in REQUIRED:
        tf_env['TF_VAR_' + key] = settings[key]
    if metadata.get('runtime_dynamic_group_ocid'):
        tf_env['TF_VAR_runtime_dynamic_group_ocid'] = metadata['runtime_dynamic_group_ocid']
        mask(metadata['runtime_dynamic_group_ocid'])
    modules = {}
    for name in ('foundation', 'iam-bootstrap'):
        module = directory / name
        shutil.copytree(root / 'infra' / name, module,
                        ignore=shutil.ignore_patterns('.terraform', '*.tfstate*', '*.tfplan'))
        modules[name] = module
        if exists:
            remote_backend(module, settings, namespace, tf_env)
        else:
            local_backend(module)
            terraform(module, ['init', '-input=false', '-lockfile=readonly'], tf_env)
    if operation == 'plan':
        return {name: plan_module(module, tf_env) for name, module in modules.items()}
    foundation = modules['foundation']
    if not exists:
        # Establish durable state before Vault/key/IAM creation. Recover a
        # partial first apply by checking bucket identity, then saving its state.
        try:
            terraform(foundation, ['apply', '-target=oci_objectstorage_bucket.state', '-auto-approve', '-input=false', '-no-color'], tf_env)
        finally:
            state = foundation / 'terraform.tfstate'
            if state.exists() and bucket_exists(storage, namespace, settings):
                storage.put_object(namespace, settings['state_bucket_name'], STATE_KEYS['foundation'],
                                   state.read_bytes(), if_none_match='*')
        remote_backend(foundation, settings, namespace, tf_env)
        remote_backend(modules['iam-bootstrap'], settings, namespace, tf_env)
    results = {}
    for name, module in modules.items():
        # On resume, complete a non-destructive ownership transfer interrupted
        # after metadata persistence. Match the actual ID before forgetting it.
        if name == 'iam-bootstrap' and metadata.get('runtime_dynamic_group_ocid'):
            state = json.loads(terraform(module, ['show', '-json'], tf_env))
            for resource in state.get('values', {}).get('root_module', {}).get('resources', []):
                if resource['address'] == 'oci_identity_dynamic_group.runtime[0]':
                    if resource['values']['id'] != metadata['runtime_dynamic_group_ocid']:
                        raise WifError('Runtime group ownership transfer identity differs.')
                    terraform(module, ['state', 'rm', 'oci_identity_dynamic_group.runtime[0]'], tf_env)
        results[name] = plan_module(module, tf_env)
        terraform(module, ['apply', '-input=false', '-no-color', 'review.tfplan'], tf_env)
    outputs = {name: json.loads(terraform(module, ['output', '-json'], tf_env)) for name, module in modules.items()}
    metadata = {'compartment_ocid': settings['compartment_ocid'],
                'runtime_dynamic_group_ocid': outputs['iam-bootstrap']['runtime_dynamic_group_ocid']['value'],
                **{k: v['value'] for k, v in outputs['foundation'].items()}}
    storage.put_object(namespace, settings['state_bucket_name'], METADATA_KEY, json.dumps(metadata).encode())
    if 'TF_VAR_runtime_dynamic_group_ocid' not in tf_env:
        terraform(modules['iam-bootstrap'], ['state', 'rm', 'oci_identity_dynamic_group.runtime[0]'], tf_env)
    return results


def main():
    directory = None
    config_path = Path.home() / '.oci' / 'config'
    try:
        env = os.environ
        hosted_runner(env)
        if env.get('HM_GITHUB_ENVIRONMENT') != 'homemovies-bootstrap' or env.get('ENABLE_HOME_MOVIES_INFRA_BOOTSTRAP') != 'true':
            raise WifError('Bootstrap requires the protected, opted-in environment.')
        operation = env.get('HOME_MOVIES_BOOTSTRAP_OPERATION')
        if operation not in ('plan', 'apply') or not env.get('GITHUB_REF', '').startswith('refs/heads/'):
            raise WifError('Select an explicit branch bootstrap plan/apply operation.')
        if config_path.exists() or config_path.is_symlink():
            raise WifError('Refusing to overwrite an existing OCI config.')
        os.umask(0o077)
        directory = Path(tempfile.mkdtemp(prefix='homemovies-wif-', dir=env['RUNNER_TEMP']))
        result = run(json.loads(env['OCI_BOOTSTRAP_SETTINGS_JSON']), json.loads(env['OCI_IAM_BOOTSTRAP_AUTH_JSON']),
                     operation, Path(__file__).resolve().parents[1], directory, config_path, env)
        print(json.dumps({'operation': operation, 'terraform_changes': result}, indent=2))
        return 0
    except Exception:
        print('Infrastructure bootstrap failed; raw details suppressed. Inspect private destination state before retrying.', file=sys.stderr)
        return 1
    finally:
        if directory is not None:
            cleanup(directory, config_path, os.environ['RUNNER_TEMP'])


if __name__ == '__main__':
    sys.exit(main())
