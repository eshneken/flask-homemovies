"""Plan/apply the destination application using permanent GitHub federation."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import oci
from cryptography.hazmat.primitives import serialization

from oci_infra_bootstrap import bucket_exists, read_metadata, summarize, terraform
from oci_wif import WifError, hosted_runner, mask, private_write, require

INPUTS = {
    'deployment_group_ocid': 'OCI_DEPLOYMENT_GROUP_OCID',
    'tenancy_ocid': 'OCI_TENANCY_OCID', 'compartment_ocid': 'OCI_COMPARTMENT_OCID',
    'compartment_name': 'OCI_COMPARTMENT_NAME', 'region': 'OCI_REGION',
    'availability_domain': 'OCI_AVAILABILITY_DOMAIN', 'image_ocid': 'OCI_IMAGE_OCID',
    'hostname': 'APP_HOSTNAME', 'acme_email': 'ACME_EMAIL',
    'bastion_client_cidrs': 'OCI_BASTION_CLIENT_CIDRS',
}

OSMH_INPUTS = {
    'osmh_enabled': ('OCI_OSMH_ENABLED', 'false'),
    'osmh_register_instance': ('OCI_OSMH_REGISTER_INSTANCE', 'false'),
    'osmh_updates_enabled': ('OCI_OSMH_UPDATES_ENABLED', 'false'),
    'osmh_update_recurring_rule': ('OCI_OSMH_UPDATE_RECURRING_RULE', 'FREQ=DAILY;INTERVAL=1'),
    'osmh_update_start': ('OCI_OSMH_UPDATE_START', ''),
    'osmh_update_hour_utc': ('OCI_OSMH_UPDATE_HOUR_UTC', '8'),
    'osmh_update_minute_utc': ('OCI_OSMH_UPDATE_MINUTE_UTC', '0'),
}


def osmh_settings(env):
    """Reject malformed switches instead of silently opting into host management."""
    settings = {key: env.get(name) or default for key, (name, default) in OSMH_INPUTS.items()}
    for key in ('osmh_enabled', 'osmh_register_instance', 'osmh_updates_enabled'):
        if settings[key] not in ('true', 'false'):
            raise WifError('OS Management Hub switches must be true or false.')
    if settings['osmh_register_instance'] == 'true' and settings['osmh_enabled'] != 'true':
        raise WifError('Prepare OS Management Hub before registering the instance.')
    if settings['osmh_updates_enabled'] == 'true' and settings['osmh_register_instance'] != 'true':
        raise WifError('Register the instance before scheduling updates.')
    if not settings['osmh_update_start']:
        del settings['osmh_update_start']  # Use Terraform's null default, never an empty timestamp.
    return settings


def verify_osmh_enrollment(plan, config, signer, settings):
    """Require a previously enrolled, active VM with only the reviewed source before scheduling."""
    if settings['osmh_updates_enabled'] != 'true':
        return
    resources = {r['address']: r['values'] for r in plan.get('planned_values', {}).get('root_module', {}).get('resources', [])}
    instance = resources.get('oci_core_instance.web', {}).get('id')
    group = resources.get('oci_os_management_hub_managed_instance_group.operating_system[0]', {}).get('id')
    source = resources.get('oci_os_management_hub_software_source.operating_system[0]', {}).get('id')
    if not all((instance, group, source)):
        raise WifError('Apply preparation and registration before scheduling OS updates.')
    managed = oci.os_management_hub.ManagedInstanceClient(config, signer=signer).get_managed_instance(instance).data
    if (managed.status != 'NORMAL' or not managed.managed_instance_group
            or managed.managed_instance_group.id != group
            or {s.id for s in (managed.software_sources or [])} != {source}):
        raise WifError('OS update scheduling requires active registration with only the reviewed OS source.')
    content = oci.os_management_hub.SoftwareSourceClient(config, signer=signer).get_software_source(source).data
    filters = getattr(content, 'custom_software_source_filter', None)
    if (content.software_source_type != 'CUSTOM' or not content.is_automatically_updated
            or content.is_auto_resolve_dependencies or not filters
            or not any(f.filter_type == 'EXCLUDE' and f.package_name_pattern == 'caddy*'
                       for f in (filters.package_filters or []))):
        raise WifError('The live OS source must refresh automatically and explicitly exclude Caddy.')


def client(env):
    """Build a security-token signer from the runner's ephemeral OCI profile."""
    config = oci.config.from_file(require(env, 'OCI_CONFIG_FILE'), 'HOMEMOVIES')
    key = serialization.load_pem_private_key(Path(config['key_file']).read_bytes(), password=None)
    token = Path(config['security_token_file']).read_text()
    return config, oci.auth.signers.SecurityTokenSigner(token, key)


def run(env, root, directory, operation):
    """Plan or apply application infrastructure against private destination state.

    Verify compartment and foundation metadata before Terraform; reject
    destructive plans and publish successful outputs in the state bucket.
    """
    settings = {key: require(env, name) for key, name in INPUTS.items()}
    settings.update(osmh_settings(env))
    settings['state_bucket_name'] = require(env, 'OCI_STATE_BUCKET_NAME')
    for name, value in settings.items():
        if name not in OSMH_INPUTS:
            mask(value)
    config, signer = client(env)
    identity = oci.identity.IdentityClient(config, signer=signer)
    compartment = identity.get_compartment(settings['compartment_ocid']).data
    if compartment.name != settings['compartment_name'] or compartment.lifecycle_state != 'ACTIVE':
        raise WifError('Application compartment is inactive or does not match its configured name.')
    storage = oci.object_storage.ObjectStorageClient(config, signer=signer)
    namespace = storage.get_namespace().data
    mask(namespace)
    if not bucket_exists(storage, namespace, settings):
        raise WifError('Complete the state foundation before application infrastructure.')
    metadata = read_metadata(storage, namespace, settings)
    for name in ('vault_ocid', 'vault_key_ocid', 'runtime_dynamic_group_ocid'):
        if not isinstance(metadata.get(name), str) or not metadata[name]:
            raise WifError('Private bootstrap outputs are incomplete.')
        mask(metadata[name])
    # Preserve the source module's relative paths to templates and deploy helper.
    module = directory / 'infra' / 'application'
    shutil.copytree(root / 'infra' / 'application', module,
                    ignore=shutil.ignore_patterns('.terraform', '*.tfstate*', '*.tfplan'))
    (directory / 'scripts').mkdir()
    shutil.copyfile(root / 'scripts' / 'vm_deploy.py', directory / 'scripts' / 'vm_deploy.py')
    tf_env = dict(env, TF_IN_AUTOMATION='true', TF_VAR_oci_auth='SecurityToken',
                  TF_VAR_config_file_profile='HOMEMOVIES')
    for name in set(INPUTS) | set(OSMH_INPUTS).intersection(settings):
        tf_env['TF_VAR_' + name] = settings[name]
    for name in ('vault_ocid', 'vault_key_ocid', 'runtime_dynamic_group_ocid'):
        tf_env['TF_VAR_' + name] = metadata[name]
    tf_env['TF_VAR_image_repository'] = 'ghcr.io/' + require(env, 'GITHUB_REPOSITORY').lower()
    backend = directory / 'backend.json'
    private_write(backend, json.dumps({'bucket': settings['state_bucket_name'], 'namespace': namespace,
                                     'key': 'application/terraform.tfstate', 'region': settings['region'],
                                     'auth': 'SecurityToken', 'config_file_profile': 'HOMEMOVIES'}))
    terraform(module, ['init', '-reconfigure', '-input=false', '-lockfile=readonly', '-backend-config=' + str(backend)], tf_env)
    terraform(module, ['plan', '-input=false', '-no-color', '-out=review.tfplan'], tf_env)
    plan = json.loads(terraform(module, ['show', '-json', 'review.tfplan'], tf_env))
    changes = summarize(plan)
    verify_osmh_enrollment(plan, config, signer, settings)
    if operation == 'apply':
        terraform(module, ['apply', '-input=false', '-no-color', 'review.tfplan'], tf_env)
        outputs = json.loads(terraform(module, ['output', '-json'], tf_env))
        body = {'compartment_ocid': settings['compartment_ocid'], **{k: v['value'] for k, v in outputs.items()}}
        storage.put_object(namespace, settings['state_bucket_name'], 'application/outputs.json', json.dumps(body).encode())
    return changes


def main():
    """Guard the infrastructure workflow, use private temporary files and clean up credentials."""
    try:
        env = os.environ
        hosted_runner(env)
        if (env.get('HM_GITHUB_ENVIRONMENT') != 'homemovies-infrastructure'
                or env.get('ENABLE_HOME_MOVIES_APPLICATION_INFRA') != 'true'
                or env.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch')
                or not env.get('GITHUB_REF', '').startswith('refs/heads/')):
            raise WifError('Use the opted-in infrastructure environment on a branch.')
        operation = env.get('HOME_MOVIES_APPLICATION_OPERATION')
        if operation not in ('plan', 'apply'):
            raise WifError('Select plan or apply.')
        os.umask(0o077)
        with tempfile.TemporaryDirectory(prefix='home-movies-terraform-', dir=require(env, 'RUNNER_TEMP')) as temporary:
            result = run(env, Path(__file__).resolve().parents[1], Path(temporary), operation)
        print(json.dumps({'operation': operation, 'terraform_changes': result}, indent=2))
        return 0
    except Exception:
        print('Application infrastructure failed; raw details suppressed. Destination state is retained for retry.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
