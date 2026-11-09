# OS Management Hub: host updates only

OS Management Hub has no additional service charge with an eligible OCI Compute
subscription. It isn't available to Free Tier instances; use a Pay As You Go
tenancy. Existing Compute/network/storage charges still apply. See
[Oracle's FAQ](https://www.oracle.com/cloud/compute/os-management/faq/) and
[prerequisites](https://docs.oracle.com/en-us/iaas/osmh/doc/getstarted.htm).

This integration manages Oracle Linux 9 ARM64 host packages and UEK R8.
**Caddy and the Python application container are excluded.** No COPR source is
registered. The custom source excludes `caddy*`; automatic dependency resolution
is disabled because it can override excludes. Oracle refreshes auto-updating
custom sources every 24 hours, so daily patching isn't an instantaneous guarantee.

## GitHub variables

Configure environment `homemovies-infrastructure`. Missing switches default to
false. Run **Home Movies application infrastructure**, operation **plan**, then
**apply**, for each stage below. Editing a variable alone doesn't change OCI.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OCI_OSMH_ENABLED` | `false` | Prepare networking, content, group, profile and IAM |
| `OCI_OSMH_REGISTER_INSTANCE` | `false` | Assign the profile and enable the plugin |
| `OCI_OSMH_UPDATES_ENABLED` | `false` | Create the recurring OS update job after enrollment verification |
| `OCI_OSMH_UPDATE_RECURRING_RULE` | `FREQ=DAILY;INTERVAL=1` | Daily or `FREQ=WEEKLY;INTERVAL=1` |
| `OCI_OSMH_UPDATE_HOUR_UTC` | `8` | UTC hour; 08 UTC is 03 EST / 04 EDT |
| `OCI_OSMH_UPDATE_MINUTE_UTC` | `0` | UTC minute |
| `OCI_OSMH_UPDATE_START` | unset | Future RFC3339 UTC start ending in `Z`, required for the job |
| `OCI_OSMH_REBOOT_ENABLED` | `false` | Opt into the conditional overnight reboot workflow |
| `OCI_OSMH_REBOOT_HOUR_UTC` | `9` | Start of reboot window; 09 UTC is 04 EST / 05 EDT |
| `OCI_OSMH_REBOOT_WINDOW_HOURS` | `2` | Reboot window duration, from one to four hours |

Make the first execution timestamp match the configured UTC hour/minute. The
service advances the next execution time; Terraform ignores that changing value
to avoid replaying the original start on unrelated applies. Change hour, minute
or frequency variables to adjust timing. Schedules use fixed UTC, not local DST.

## Rollout

1. Apply the reviewed `infra/iam-bootstrap` change using the existing bootstrap
   procedure in [GitHub Actions](github-actions.md). It adds infrastructure-group
   read access to root-compartment OSMH sources and profiles. Existing application
   management permissions cover project resources. No tenancy-wide OSMH write
   access or on-premises Management Agent keys are needed.
2. Set only `OCI_OSMH_ENABLED=true` and apply. This creates private service-network
   routing, five vendor-source replicas, an auto-updating custom OS source, a
   managed-instance group, a non-default group profile and self-only instance
   IAM. There is no management-station VM, new public IP or additional ingress.
3. Through [managed SSH](vm-maintenance.md), verify Oracle Cloud Agent is at least
   1.40 (`rpm -q oracle-cloud-agent`). Record `rpm -q caddy` and `uname -r`.
   As an additional safeguard, add `caddy*` to `[main]` `excludepkgs` in
   `/etc/dnf/dnf.conf`, preserving any existing exclusions. Check for a competing
   `dnf-automatic` updater; don't disable Oracle Cloud Agent's own updater.
4. Set `OCI_OSMH_REGISTER_INSTANCE=true` and apply. The VM receives the
   `OsmhProfile` tag and enables the OS Management Hub Agent plugin. Bastion,
   Run Command, private addressing and mandatory IMDSv2 remain configured.
   Wait up to ten minutes; in **OS Management Hub → Instances**, verify Active,
   the Home Movies group, and only the filtered OS source.
5. If the existing VM doesn't pick up the profile tag, choose this project's
   profile explicitly under **Compute → instance → Management → Oracle Cloud
   Agent → OS Management Hub Agent**. Don't choose a default profile that could
   attach unreviewed content. Investigate agent logs before proceeding.
6. Set a future `OCI_OSMH_UPDATE_START` and `OCI_OSMH_UPDATES_ENABLED=true`, then
   plan/apply. The workflow checks live enrollment and source attachment before
   scheduling. It deliberately rejects applying all stages at once. The job
   applies all OS update categories with three retries five minutes apart.
7. Run `home-movies-os-updates` immediately using the OCI CLI
   `os-management-hub scheduled-job run-now --scheduled-job-id <job-ocid>` and
   inspect its log. This preserves the job association used by the reboot check. Verify
   `systemctl is-active home-movies caddy`, public HTTPS `/health`, that
   `rpm -q caddy` is unchanged, and the Hub's reboot-required indicator.
8. Set `OCI_OSMH_REBOOT_ENABLED=true` once the update job and private outputs are
   available. The maintenance workflow runs from `main` and checks the UTC window
   hourly. A manual run uses the same window and safety checks, not an override.
   Repository/environment configuration is sufficient to adjust the window.

The reviewed vendor sources are BaseOS latest, AppStream, Addons, UEK R8 and OCI
included packages for OL9 ARM64. Terraform discovers their regional identifiers.
The group gets only the custom source, never raw vendors or third-party sources.

## Reboots and monitoring

Package installation doesn't activate a newly installed kernel. The separate
conditional reboot workflow uses short-lived GitHub/OCI federation and reads
private Terraform outputs rather than hardcoded instance identifiers. It requires
an active instance, the reviewed Caddy-excluding source, a reboot-required flag,
and a recent successful execution of this VM's OS update job. Failed, running or
stale updates defer the reboot. It also checks for active OSMH operations and
follows child work requests to the overall scheduled execution before accepting
its success. It checks
public HTTPS health, rechecks the window immediately before submitting, and uses
an ETag and stable retry token to avoid conflicting or duplicate requests.

After submitting a managed reboot, it waits for the reboot job to succeed, a new
boot timestamp, the reboot-required flag to clear and public HTTPS to recover.
Failure marks the GitHub workflow failed; enable GitHub Actions failure
notifications for this repository. The default 09–11 UTC window is 04–06 EST /
05–07 EDT. GitHub schedule delivery can be delayed; a run outside the window skips
the reboot. Infrastructure changes, app deployment and this workflow share a
concurrency group. No credentials are requested outside the maintenance window.

Ksplice is a separate opt-in requiring its sources and client; it isn't enabled
here. Until registration, updates and the reboot workflow are enabled, use
[VM maintenance](vm-maintenance.md) for host updates/reboots.

Job history and instance status are the OSMH monitoring surface. OCI notifications
need a separately configured topic/subscription; no email subscription is created.
Application-container patches still require an image rebuild and deployment.

To pause automatic reboots, set `OCI_OSMH_REBOOT_ENABLED=false`. For a temporary
patching pause, move the scheduled job's next run in the Console and record/
reconcile the change before another Terraform apply.
Ordinary infrastructure applies reject deletions, including switches that would
destroy OSMH resources. Permanent removal requires a reviewed teardown. Don't
delete the source/profile while the instance is enrolled. Keep Caddy's existing
installation/repository for separate maintenance.

References: [registration](https://docs.oracle.com/en-us/iaas/osmh/doc/register-oci-instance.htm),
[update jobs](https://docs.oracle.com/en-us/iaas/osmh/doc/create-scheduled-job-instance.htm),
[custom sources](https://docs.oracle.com/en-us/iaas/osmh/doc/custom-software-source.htm),
[exclude caveat](https://docs.oracle.com/en-us/iaas/osmh/doc/known-issues.htm).
