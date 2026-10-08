"""Submit a digest-only deployment through OCI Run Command; no SSH credentials."""
import os
import sys
import time

import oci

from oci_application_infra import client
from oci_wif import WifError, hosted_runner, mask, require
from vm_deploy import validate_image


def deploy(env, compute, agent):
    instance_id = require(env, 'OCI_INSTANCE_OCID')
    compartment_id = require(env, 'OCI_COMPARTMENT_OCID')
    mask(instance_id)
    mask(compartment_id)
    instance = compute.get_instance(instance_id).data
    if instance.compartment_id != compartment_id or instance.lifecycle_state != 'RUNNING':
        raise WifError('Deployment target is not a running instance in the application compartment.')
    repository = 'ghcr.io/' + require(env, 'GITHUB_REPOSITORY').lower()
    image = validate_image(require(env, 'APP_IMAGE'), repository)
    model = oci.compute_instance_agent.models
    command = agent.create_instance_agent_command(model.CreateInstanceAgentCommandDetails(
        compartment_id=compartment_id, execution_time_out_in_seconds=300,
        display_name='home-movies-deploy',
        target=model.InstanceAgentCommandTarget(instance_id=instance_id),
        content=model.InstanceAgentCommandContent(
            source=model.InstanceAgentCommandSourceViaTextDetails(
                text='#!/bin/sh\nset -eu\nsudo -n /usr/local/sbin/home-movies-deploy ' + image + '\n'),
            output=model.InstanceAgentCommandOutputViaTextDetails()))).data
    mask(command.id)
    deadline = time.monotonic() + 480
    while time.monotonic() < deadline:
        try:
            execution = agent.get_instance_agent_command_execution(command.id, instance_id).data
        except oci.exceptions.ServiceError as error:
            if error.status != 404:
                raise
            # Delivery is asynchronous: the execution may not exist yet.
            time.sleep(10)
            continue
        if execution.lifecycle_state == 'SUCCEEDED':
            return
        if execution.lifecycle_state in ('FAILED', 'TIMED_OUT', 'CANCELED'):
            raise WifError('Run Command deployment did not succeed; inspect its private output in OCI.')
        time.sleep(10)
    raise WifError('Run Command deployment timed out; inspect execution in OCI before retrying.')


def main():
    try:
        env = os.environ
        hosted_runner(env)
        if (env.get('HM_GITHUB_ENVIRONMENT') != 'homemovies-production'
                or env.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch')
                or not env.get('GITHUB_REF', '').startswith('refs/heads/')):
            raise WifError('Use the production deployment environment on a branch.')
        config, signer = client(env)
        deploy(env, oci.core.ComputeClient(config, signer=signer),
               oci.compute_instance_agent.ComputeInstanceAgentClient(config, signer=signer))
        print('Application deployment passed the VM local health check.')
        return 0
    except Exception:
        print('Application deployment failed; raw details suppressed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
