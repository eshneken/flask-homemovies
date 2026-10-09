import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import oci

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oci_app_deploy as release
from oci_wif import WifError

ENV = dict(OCI_INSTANCE_OCID='test-instance', OCI_COMPARTMENT_OCID='test-compartment',
           GITHUB_REPOSITORY='example/home-movies', APP_IMAGE='ghcr.io/example/home-movies@sha256:' + 'a' * 64)


class RunCommandTests(unittest.TestCase):
    def clients(self):
        compute, agent = Mock(), Mock()
        compute.get_instance.return_value.data = NS(compartment_id='test-compartment', lifecycle_state='RUNNING')
        agent.create_instance_agent_command.return_value.data = NS(id='test-command')
        agent.get_instance_agent_command_execution.return_value.data = NS(lifecycle_state='SUCCEEDED')
        return compute, agent

    def test_digest_only_command_and_private_target(self):
        compute, agent = self.clients()
        with patch.object(release, 'mask'):
            release.deploy(ENV, compute, agent)
        submitted = agent.create_instance_agent_command.call_args.args[0]
        self.assertEqual(submitted.target.instance_id, 'test-instance')
        self.assertEqual(submitted.compartment_id, 'test-compartment')
        self.assertEqual(submitted.execution_time_out_in_seconds, 600)
        self.assertEqual(submitted.content.source.text, '#!/bin/sh\nset -eu\nsudo -n /usr/local/sbin/home-movies-deploy ' + ENV['APP_IMAGE'] + '\n')
        self.assertEqual(submitted.content.source.source_type, 'TEXT')
        agent.get_instance_agent_command_execution.assert_called_once_with('test-command', 'test-instance')

    def test_wrong_target_and_unsafe_image_never_submit(self):
        for compartment, state, image in (('other', 'RUNNING', ENV['APP_IMAGE']),
                                          ('test-compartment', 'STOPPED', ENV['APP_IMAGE']),
                                          ('test-compartment', 'RUNNING', ENV['APP_IMAGE'] + ';id')):
            compute, agent = self.clients()
            compute.get_instance.return_value.data = NS(compartment_id=compartment, lifecycle_state=state)
            with patch.object(release, 'mask'), self.assertRaises(Exception):
                release.deploy(dict(ENV, APP_IMAGE=image), compute, agent)
            agent.create_instance_agent_command.assert_not_called()

    def test_waits_for_delivery_and_reports_terminal_failures(self):
        for state in ('SUCCEEDED', 'FAILED', 'TIMED_OUT', 'CANCELED'):
            compute, agent = self.clients()
            not_delivered = oci.exceptions.ServiceError(404, 'NotFound', {}, '<private-output>')
            agent.get_instance_agent_command_execution.side_effect = [not_delivered, NS(data=NS(lifecycle_state='IN_PROGRESS')), NS(data=NS(lifecycle_state=state))]
            with patch.object(release, 'mask'), patch.object(release.time, 'sleep') as sleep:
                if state == 'SUCCEEDED':
                    release.deploy(ENV, compute, agent)
                else:
                    with self.assertRaises(WifError):
                        release.deploy(ENV, compute, agent)
                self.assertEqual(sleep.call_count, 2)

    def test_permission_errors_and_timeout_are_not_success(self):
        compute, agent = self.clients()
        agent.get_instance_agent_command_execution.side_effect = oci.exceptions.ServiceError(403, 'NotAuthorized', {}, '<private-output>')
        with patch.object(release, 'mask'), self.assertRaises(oci.exceptions.ServiceError):
            release.deploy(ENV, compute, agent)

        with patch.object(release, 'mask'), patch.object(release.time, 'monotonic', side_effect=[0, 901]), self.assertRaises(WifError):
            release.deploy(ENV, compute, agent)

    def test_initial_pull_and_late_result_can_exceed_eight_minutes(self):
        compute, agent = self.clients()
        agent.get_instance_agent_command_execution.side_effect = [
            NS(data=NS(lifecycle_state=state)) for state in ('ACCEPTED', 'IN_PROGRESS', 'SUCCEEDED')]
        with patch.object(release, 'mask'), patch.object(release.time, 'sleep'), \
                patch.object(release.time, 'monotonic', side_effect=[0, 10, 500, 850]):
            release.deploy(ENV, compute, agent)
        self.assertEqual(agent.get_instance_agent_command_execution.call_count, 3)

    def test_main_requires_production_branch_and_sanitizes_sdk_failures(self):
        env = dict(ENV, GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                   HM_GITHUB_ENVIRONMENT='homemovies-production', GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/test')
        for change in ({'HM_GITHUB_ENVIRONMENT': 'homemovies-infrastructure'}, {'GITHUB_EVENT_NAME': 'pull_request'}, {'GITHUB_REF': 'refs/tags/test'}):
            with patch.dict(os.environ, dict(env, **change), clear=True), patch('builtins.print'), patch.object(release, 'client') as client:
                self.assertEqual(release.main(), 1)
                client.assert_not_called()
        for failed in (False, True):
            with patch.dict(os.environ, env, clear=True), patch.object(release, 'client', return_value=({}, Mock())), \
                    patch.object(release, 'deploy') as deploy, patch('builtins.print') as log, \
                    patch.object(release.oci.core, 'ComputeClient'), \
                    patch.object(release.oci.compute_instance_agent, 'ComputeInstanceAgentClient'):
                if failed:
                    deploy.side_effect = RuntimeError('<private-output>')
                self.assertEqual(release.main(), 1 if failed else 0)
                self.assertNotIn('<private-output>', log.call_args.args[0])
