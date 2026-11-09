"""Reboot only this VM, overnight, after successful OS patching requires it."""
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone


def in_window(env, now):
    """Use a bounded UTC maintenance window, including windows across midnight."""
    start = int(env.get('OCI_OSMH_REBOOT_HOUR_UTC') or '9')
    duration = int(env.get('OCI_OSMH_REBOOT_WINDOW_HOURS') or '2')
    if not 0 <= start <= 23 or not 1 <= duration <= 4:
        raise ValueError('Invalid UTC maintenance window.')
    return (now.hour - start) % 24 < duration


def window_output(env, now):
    """Skip authentication outside the maintenance window."""
    active = (env.get('OCI_OSMH_REBOOT_ENABLED') == 'true'
              and env.get('OCI_OSMH_UPDATES_ENABLED') == 'true' and in_window(env, now))
    with open(env['GITHUB_OUTPUT'], 'a') as stream:
        stream.write('run=' + str(active).lower() + '\n')
    return 0


def healthy(hostname):
    """Verify public HTTPS without exposing a configured hostname in errors."""
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]+[a-zA-Z0-9]', hostname):
        return False
    try:
        with urllib.request.urlopen('https://' + hostname + '/health', timeout=15) as response:
            return response.status == 200
    except Exception:
        return False


def maintain(env, outputs, compute, managed, jobs, work, reboot_details, now):
    """Fail closed on wrong targets, source drift, failed updates or concurrent jobs."""
    instance_id, compartment = outputs['instance_ocid'], outputs['compartment_ocid']
    target = compute.get_instance(instance_id).data
    if target.compartment_id != compartment or target.lifecycle_state != 'RUNNING':
        raise ValueError('The maintenance target is not the configured running VM.')
    if not in_window(env, now):
        return 'outside maintenance window'
    record = managed.get_managed_instance(instance_id)
    instance = record.data
    if instance.compartment_id != compartment or instance.status != 'NORMAL':
        raise ValueError('OS Management Hub instance is not active in the target compartment.')
    if not instance.is_reboot_required:
        return 'no reboot required'
    job_id = outputs['osmh_update_job_ocid']
    job = jobs.get_scheduled_job(job_id).data
    if (job.compartment_id != compartment or job.managed_instance_ids != [instance_id]
            or job.managed_instance_group_ids or job.managed_compartment_ids
            or [o.operation_type for o in job.operations] != ['UPDATE_ALL']):
        raise ValueError('The patch job must target only the configured VM and OS updates.')
    requests = work.list_work_requests(compartment_id=compartment, resource_id=instance_id,
        initiator_id=job_id, sort_by='timeCreated', sort_order='DESC', limit=1).data.items
    if not requests:
        return 'waiting for first update job'
    update = work.get_work_request(requests[0].id).data
    # OCI expands scheduled updates into nested work requests. Resolve
    # the overall execution so one successful child cannot authorize a reboot.
    seen = {requests[0].id}
    for _ in range(10):
        if update.compartment_id != compartment or update.initiator_id != job_id:
            raise ValueError('The OS update execution belongs to a different job or compartment.')
        if not update.parent_id:
            break
        if update.parent_id in seen:
            raise ValueError('The OS update execution has a cyclic parent chain.')
        seen.add(update.parent_id)
        update = work.get_work_request(update.parent_id).data
    else:
        raise ValueError('The OS update execution parent chain is too deep.')
    if update.operation_type != 'UPDATE_ALL_PACKAGES':
        raise ValueError('The overall execution must be an OS package update.')
    if update.status != 'SUCCEEDED' or not update.time_finished:
        raise ValueError('The latest OS update has not succeeded; reboot deferred.')
    age = now - update.time_finished
    max_age = timedelta(days=8) if env.get('OCI_OSMH_UPDATE_RECURRING_RULE', '').startswith('FREQ=WEEKLY;') else timedelta(hours=26)
    if age < timedelta(0) or age > max_age:
        raise ValueError('No recent successful OS update; reboot deferred.')
    if instance.time_last_boot and instance.time_last_boot >= update.time_finished:
        return 'already rebooted after latest update'
    pending = work.list_work_requests(compartment_id=compartment, resource_id=instance_id,
        status=['ACCEPTED', 'IN_PROGRESS', 'CANCELING'], limit=1).data.items
    if pending:
        raise ValueError('Another host operation is pending; reboot deferred.')
    if not healthy(env['APP_HOSTNAME']):
        raise ValueError('Pre-reboot HTTPS health check failed.')
    # Recheck the wall clock after API calls, and use the instance ETag to reject
    # a concurrent management change. A stable retry token prevents duplicates.
    if not in_window(env, datetime.now(timezone.utc)):
        return 'maintenance window ended'
    token = hashlib.sha256((instance_id + update.id).encode()).hexdigest()
    response = managed.reboot_managed_instance(instance_id, reboot_details,
        if_match=record.headers['etag'], opc_retry_token=token)
    reboot_id = response.headers['opc-work-request-id']
    for _ in range(60):
        result = work.get_work_request(reboot_id).data
        if result.status in ('FAILED', 'CANCELED'):
            raise ValueError('The managed reboot failed; inspect its private job log.')
        if result.status == 'SUCCEEDED':
            current = managed.get_managed_instance(instance_id).data
            if (current.time_last_boot and current.time_last_boot > now
                    and not current.is_reboot_required and healthy(env['APP_HOSTNAME'])):
                return 'reboot completed; HTTPS healthy'
        time.sleep(20)
    raise ValueError('Reboot or post-reboot verification timed out.')


def main():
    """Run only from the opted-in protected main-branch maintenance workflow."""
    try:
        env = os.environ
        now = datetime.now(timezone.utc)
        if sys.argv[1:] == ['window']:
            return window_output(env, now)
        from oci_wif import hosted_runner, require
        from oci_application_infra import client, verify_osmh_enrollment
        import oci
        hosted_runner(env)
        if (env.get('GITHUB_REF') != 'refs/heads/main'
                or env.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch')
                or env.get('HM_GITHUB_ENVIRONMENT') != 'homemovies-infrastructure'
                or env.get('OCI_OSMH_REBOOT_ENABLED') != 'true'
                or env.get('OCI_OSMH_UPDATES_ENABLED') != 'true'):
            raise ValueError('Use the opted-in protected maintenance workflow on main.')
        config, signer = client(env)
        storage = oci.object_storage.ObjectStorageClient(config, signer=signer)
        namespace = storage.get_namespace().data
        outputs = json.loads(storage.get_object(namespace, require(env, 'OCI_STATE_BUCKET_NAME'),
                                                 'application/outputs.json').data.content)
        if outputs['compartment_ocid'] != require(env, 'OCI_COMPARTMENT_OCID'):
            raise ValueError('Private outputs belong to a different compartment.')
        # Share the enrollment/content checks used before enabling update jobs.
        plan = {'planned_values': {'root_module': {'resources': [
            {'address': address, 'values': {'id': outputs[key]}} for address, key in [
                ('oci_core_instance.web', 'instance_ocid'),
                ('oci_os_management_hub_managed_instance_group.operating_system[0]', 'osmh_group_ocid'),
                ('oci_os_management_hub_software_source.operating_system[0]', 'osmh_source_ocid')]]}}}
        verify_osmh_enrollment(plan, config, signer, {'osmh_updates_enabled': 'true'})
        result = maintain(env, outputs, oci.core.ComputeClient(config, signer=signer),
            oci.os_management_hub.ManagedInstanceClient(config, signer=signer),
            oci.os_management_hub.ScheduledJobClient(config, signer=signer),
            oci.os_management_hub.WorkRequestClient(config, signer=signer),
            oci.os_management_hub.models.RebootManagedInstanceDetails(reboot_timeout_in_mins=20), now)
        print(result)
        return 0
    except Exception:
        print('OS maintenance failed; private details suppressed. Check the OCI job log.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
