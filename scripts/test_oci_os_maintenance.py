import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import oci

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oci_application_infra as infrastructure
import oci_os_maintenance as maintenance

NOW = datetime(2030, 1, 2, 9, 23, tzinfo=timezone.utc)
ENV = dict(APP_HOSTNAME='movies.example.com', OCI_OSMH_REBOOT_ENABLED='true', OCI_OSMH_UPDATES_ENABLED='true')
OUTPUTS = dict(instance_ocid='vm', compartment_ocid='compartment', osmh_group_ocid='group',
               osmh_source_ocid='source', osmh_update_job_ocid='job')


def update_result(**changes):
    values = dict(id='update', status='SUCCEEDED', time_finished=NOW-timedelta(minutes=40),
                  compartment_id='compartment', initiator_id='job', parent_id=None,
                  operation_type='UPDATE_ALL_PACKAGES')
    return NS(**dict(values, **changes))


class MaintenanceTests(unittest.TestCase):
    def clients(self):
        compute, managed, jobs, work = [Mock() for _ in range(4)]
        compute.get_instance.return_value.data = NS(compartment_id='compartment', lifecycle_state='RUNNING')
        managed.get_managed_instance.return_value = NS(headers={'etag': 'version'}, data=NS(
            compartment_id='compartment', status='NORMAL', is_reboot_required=True,
            time_last_boot=NOW-timedelta(days=2)))
        jobs.get_scheduled_job.return_value.data = NS(compartment_id='compartment', managed_instance_ids=['vm'],
            managed_instance_group_ids=[], managed_compartment_ids=[], operations=[NS(operation_type=operation) for operation in maintenance.OS_UPDATE_OPERATIONS])
        work.list_work_requests.side_effect = [NS(data=NS(items=[NS(id='update')])), NS(data=NS(items=[]))]
        update = update_result()
        work.get_work_request.side_effect = lambda request: NS(data=update if request == 'update' else NS(status='SUCCEEDED'))
        managed.reboot_managed_instance.return_value.headers = {'opc-work-request-id': 'reboot'}
        return compute, managed, jobs, work

    def run_maintenance(self, clients, env=None):
        with patch.object(maintenance, 'healthy', return_value=True), patch.object(maintenance, 'datetime') as clock:
            clock.now.return_value = NOW
            return maintenance.maintain(env or ENV, OUTPUTS, *clients, Mock(), NOW)

    def test_window_bounds_cross_midnight_and_opt_in(self):
        self.assertTrue(maintenance.in_window({}, NOW))
        self.assertFalse(maintenance.in_window({}, NOW.replace(hour=11)))
        self.assertTrue(maintenance.in_window(dict(OCI_OSMH_REBOOT_HOUR_UTC='23'), NOW.replace(hour=0)))
        for env in [dict(OCI_OSMH_REBOOT_HOUR_UTC='24'), dict(OCI_OSMH_REBOOT_WINDOW_HOURS='0'),
                    dict(OCI_OSMH_REBOOT_WINDOW_HOURS='5')]:
            with self.assertRaises(ValueError): maintenance.in_window(env, NOW)
        with tempfile.TemporaryDirectory() as root:
            f=Path(root)/'output'
            maintenance.window_output(dict(ENV, GITHUB_OUTPUT=str(f)), NOW)
            maintenance.window_output(dict(GITHUB_OUTPUT=str(f)), NOW)
            self.assertEqual(f.read_text(), 'run=true\nrun=false\n')

    def test_health_checks_validate_tls_hostname_and_handle_errors(self):
        self.assertFalse(maintenance.healthy('bad/path'))
        with patch.object(maintenance.urllib.request, 'urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            self.assertTrue(maintenance.healthy(ENV['APP_HOSTNAME']))
            urlopen.return_value.__enter__.return_value.status = 503
            self.assertFalse(maintenance.healthy(ENV['APP_HOSTNAME']))
            urlopen.side_effect = OSError('private')
            self.assertFalse(maintenance.healthy(ENV['APP_HOSTNAME']))

    def test_no_unneeded_or_outside_window_reboot(self):
        clients=self.clients();clients[1].get_managed_instance.return_value.data.is_reboot_required=False
        self.assertEqual(self.run_maintenance(clients), 'no reboot required')
        clients[1].reboot_managed_instance.assert_not_called()
        self.assertEqual(self.run_maintenance(self.clients(), dict(ENV, OCI_OSMH_REBOOT_HOUR_UTC='1')), 'outside maintenance window')

    def test_wrong_target_or_inactive_instance_is_rejected(self):
        for target, key, value in [(0,'compartment_id','other'), (0,'lifecycle_state','STOPPED'),
                                   (1,'compartment_id','other'), (1,'status','UNREACHABLE')]:
            clients=self.clients();api=clients[target]
            record=api.get_instance.return_value.data if target==0 else api.get_managed_instance.return_value.data
            setattr(record,key,value)
            with self.assertRaises(ValueError): self.run_maintenance(clients)
            clients[1].reboot_managed_instance.assert_not_called()

    def test_wrong_patch_job_is_rejected(self):
        for key,value in [('compartment_id','other'), ('managed_instance_ids',['other']),
                          ('managed_instance_group_ids',['group']), ('managed_compartment_ids',['compartment']),
                          ('operations',[NS(operation_type='REBOOT')]),
                          ('operations',[NS(operation_type='UPDATE_ALL')]),
                          ('operations',[NS(operation_type=operation) for operation in maintenance.OS_UPDATE_OPERATIONS[:-1]]),
                          ('operations',[NS(operation_type=operation) for operation in (*maintenance.OS_UPDATE_OPERATIONS,'UPDATE_KSPLICE_USERSPACE')])]:
            clients=self.clients();setattr(clients[2].get_scheduled_job.return_value.data,key,value)
            with self.assertRaises(ValueError): self.run_maintenance(clients)

    def test_missing_failed_stale_or_future_update_does_not_reboot(self):
        clients=self.clients();clients[3].list_work_requests.side_effect=[NS(data=NS(items=[]))]
        self.assertEqual(self.run_maintenance(clients),'waiting for first update job')
        for status,finished in [('FAILED',NOW), ('SUCCEEDED',None), ('SUCCEEDED',NOW-timedelta(days=2)),
                                ('SUCCEEDED',NOW+timedelta(minutes=1))]:
            clients=self.clients();clients[3].get_work_request.side_effect=None
            clients[3].get_work_request.return_value.data=update_result(status=status,time_finished=finished)
            with self.assertRaises(ValueError): self.run_maintenance(clients)

    # Value: protects=weekly update freshness permits two-day-old success but rejects nine days;
    # fails_when=weekly freshness uses the daily limit or stale updates are accepted;
    # why_new=the previous weekly case used a 40-minute-old update; seam=none;
    # no_claim=OCI timestamp fields are represented by local aware datetime fixtures.
    def test_weekly_updates_and_already_completed_reboot(self):
        for frequency, age_days, accepted in [('WEEKLY', 2, True), ('DAILY', 2, False), ('WEEKLY', 9, False)]:
            with self.subTest(frequency=frequency, age_days=age_days):
                clients=self.clients();clients[1].get_managed_instance.return_value.data.time_last_boot=NOW
                clients[3].get_work_request.side_effect=None
                clients[3].get_work_request.return_value.data=update_result(time_finished=NOW-timedelta(days=age_days))
                env=dict(ENV,OCI_OSMH_UPDATE_RECURRING_RULE='FREQ=' + frequency + ';INTERVAL=1')
                if accepted:
                    self.assertEqual(self.run_maintenance(clients,env),'already rebooted after latest update')
                else:
                    with self.assertRaises(ValueError): self.run_maintenance(clients,env)
                clients[1].reboot_managed_instance.assert_not_called()

    def test_successful_child_cannot_authorize_failed_or_pending_overall_update(self):
        for status in ['FAILED', 'IN_PROGRESS', 'CANCELED']:
            with self.subTest(status=status):
                clients=self.clients()
                results={'update': update_result(parent_id='root'),
                         'root': update_result(id='root',status=status)}
                clients[3].get_work_request.side_effect=lambda request: NS(data=results[request])
                with self.assertRaisesRegex(ValueError,'latest OS update'):
                    self.run_maintenance(clients)
                clients[1].reboot_managed_instance.assert_not_called()

    def test_nested_update_uses_overall_completion_and_stable_reboot_identity(self):
        tokens=[]
        for leaf in ['update', 'other-child']:
            clients=self.clients()
            clients[3].list_work_requests.side_effect=[NS(data=NS(items=[NS(id=leaf)])),NS(data=NS(items=[]))]
            results={leaf: update_result(id=leaf,parent_id='middle'),
                     'middle': update_result(id='middle',parent_id='root'),
                     'root': update_result(id='root')}
            clients[3].get_work_request.side_effect=lambda request: NS(data=results[request] if request in results else NS(status='SUCCEEDED'))
            record=clients[1].get_managed_instance.return_value
            clients[1].get_managed_instance.side_effect=[record,NS(data=NS(time_last_boot=NOW+timedelta(minutes=1),is_reboot_required=False))]
            self.assertEqual(self.run_maintenance(clients),'reboot completed; HTTPS healthy')
            tokens.append(clients[1].reboot_managed_instance.call_args.kwargs['opc_retry_token'])
        self.assertEqual(tokens[0],tokens[1])

    def test_invalid_overall_update_ancestry_fails_closed(self):
        for change in [dict(initiator_id='other-job'),dict(compartment_id='other'),
                       dict(operation_type='REBOOT'),dict(parent_id='update')]:
            with self.subTest(change=change):
                clients=self.clients()
                results={'update': update_result(parent_id='root'),'root': update_result(id='root',**change)}
                clients[3].get_work_request.side_effect=lambda request: NS(data=results[request])
                with self.assertRaises(ValueError): self.run_maintenance(clients)
                clients[1].reboot_managed_instance.assert_not_called()
        clients=self.clients()
        clients[3].get_work_request.side_effect=lambda request: NS(data=update_result(id=request,parent_id=request+'-parent'))
        with self.assertRaisesRegex(ValueError,'too deep'): self.run_maintenance(clients)
        clients[1].reboot_managed_instance.assert_not_called()

    def test_concurrent_job_or_bad_health_blocks_reboot(self):
        clients=self.clients();clients[3].list_work_requests.side_effect=[NS(data=NS(items=[NS(id='update')])),NS(data=NS(items=[NS(id='busy')]))]
        with self.assertRaises(ValueError): self.run_maintenance(clients)
        with patch.object(maintenance,'healthy',return_value=False),self.assertRaises(ValueError):
            maintenance.maintain(ENV,OUTPUTS,*self.clients(),Mock(),NOW)

    def test_ending_window_defers_reboot(self):
        clients=self.clients()
        with patch.object(maintenance,'healthy',return_value=True), patch.object(maintenance,'datetime') as clock:
            clock.now.return_value=NOW.replace(hour=11)
            self.assertEqual(maintenance.maintain(ENV,OUTPUTS,*clients,Mock(),NOW),'maintenance window ended')

    def test_successful_reboot_requires_new_boot_and_https(self):
        clients=self.clients();record=clients[1].get_managed_instance.return_value
        clients[1].get_managed_instance.side_effect=[record,NS(data=NS(time_last_boot=NOW+timedelta(minutes=1),is_reboot_required=False))]
        self.assertEqual(self.run_maintenance(clients),'reboot completed; HTTPS healthy')
        self.assertEqual(clients[1].reboot_managed_instance.call_args.kwargs['if_match'],'version')
        self.assertEqual(len(clients[1].reboot_managed_instance.call_args.kwargs['opc_retry_token']),64)

    # Value: protects=a successful job cannot claim reboot recovery without boot, flag and HTTPS evidence;
    # fails_when=any post-reboot verification guard is removed; why_new=the old timeout kept the job IN_PROGRESS;
    # seam=none; no_claim=real OCI reboot completion and public HTTPS recovery are not exercised.
    def test_failed_or_unverified_reboot_fails(self):
        for status in ['FAILED','CANCELED','IN_PROGRESS']:
            clients=self.clients();update=update_result()
            clients[3].get_work_request.side_effect=lambda request: NS(data=update if request=='update' else NS(status=status))
            with patch.object(maintenance.time,'sleep'),self.assertRaises(ValueError): self.run_maintenance(clients)
        for missing_evidence in ['new_boot', 'reboot_flag', 'https']:
            with self.subTest(missing_evidence=missing_evidence):
                clients=self.clients();record=clients[1].get_managed_instance.return_value
                current=NS(time_last_boot=NOW-timedelta(minutes=1) if missing_evidence=='new_boot' else NOW+timedelta(minutes=1),
                           is_reboot_required=missing_evidence=='reboot_flag')
                clients[1].get_managed_instance.side_effect=[record]+[NS(data=current)]*60
                with patch.object(maintenance.time,'sleep'), patch.object(maintenance,'healthy') as health, \
                        patch.object(maintenance,'datetime') as clock, self.assertRaisesRegex(ValueError,'verification timed out'):
                    clock.now.return_value=NOW
                    health.side_effect=[True]+[missing_evidence!='https']*60
                    maintenance.maintain(ENV,OUTPUTS,*clients,Mock(),NOW)

    def test_main_window_and_protected_workflow_boundary(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,dict(GITHUB_OUTPUT=str(Path(root)/'output')),clear=True),patch.object(sys,'argv',['script','window']):
            self.assertEqual(maintenance.main(),0)
        env=dict(ENV,GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',GITHUB_REF='refs/heads/main',
                 GITHUB_EVENT_NAME='schedule',HM_GITHUB_ENVIRONMENT='homemovies-infrastructure',
                 OCI_STATE_BUCKET_NAME='bucket',OCI_COMPARTMENT_OCID='compartment')
        storage=Mock();storage.get_namespace.return_value.data='namespace'
        storage.get_object.return_value.data.content=json.dumps(OUTPUTS).encode()
        for change,expected in [({},0),({'GITHUB_REF':'refs/heads/other'},1),({'OCI_OSMH_REBOOT_ENABLED':'false'},1),
                                ({'OCI_COMPARTMENT_OCID':'other'},1)]:
            with patch.dict(os.environ,dict(env,**change),clear=True),patch.object(sys,'argv',['script']), \
                    patch.object(infrastructure,'client',return_value=({},None)), \
                    patch.object(infrastructure,'verify_osmh_enrollment'), \
                    patch.object(oci.object_storage,'ObjectStorageClient',return_value=storage), \
                    patch.object(oci.core,'ComputeClient'), \
                    patch.object(oci.os_management_hub,'ManagedInstanceClient'), \
                    patch.object(oci.os_management_hub,'ScheduledJobClient'), \
                    patch.object(oci.os_management_hub,'WorkRequestClient'), \
                    patch.object(maintenance,'maintain',return_value='no reboot required'),patch('builtins.print'):
                self.assertEqual(maintenance.main(),expected)
