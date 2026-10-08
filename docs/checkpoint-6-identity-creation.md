# Checkpoint 6 — dedicated identities with the existing GitHub trust

Status: complete. Dedicated identities exist and the shared trust update is verified.

Subsequent owner preference: GitHub reviewer gates were removed during
Checkpoint 7. Historical approval instructions below describe the completed
identity setup; future plans/applies proceed automatically between chat checkpoints.

The owner-approved [shared-trust workflow](https://github.com/eshneken/flask-homemovies/actions/runs/37850807415)
succeeded. A subsequent read-only inventory found zero remaining changes and
verified that the original grocery OAuth client, audience, service-user mapping,
trust identity and verification controls were preserved. Both exact Home Movies
environment mappings are present. The one-time apply trigger is now disabled.
The production environment's verified deployment service-user OCID is configured
as `OCI_WIF_SERVICE_USER_OCID`; its value is not committed or printed.

No OCI workload IAM grants, infrastructure resources or source changes were made.
Permanent WIF verification remains disabled until the IAM bootstrap checkpoint.

## Initial attempt and correction

The approved run created both service users and both groups, but OCI rejected
the trust because its GitHub issuer already belongs to the grocery trust in the
destination Default domain. A read-only inventory and the domain audit event
verified this result. No IAM policies or workload infrastructure were created;
the grocery trust was not modified. The one-time apply trigger was disabled.

The original plan missed issuer uniqueness within the domain. The planner now
checks this before any writes, with a regression test. The owner explicitly
selected reuse of the grocery trust in the same domain. No additional identity
domain or confidential application is needed. The existing Home Movies users
and groups currently have no workload permissions and will be reused.

The revised read-only plan finds zero identities or trusts to create and one
existing trust to update. This checkpoint implements the writes through a separate
GitHub Actions workflow on the migration branch. It uses the existing protected
`homemovies-bootstrap` environment and its temporary administrator application.

## Review the exact changes

| Resource | Purpose |
|---|---|
| Service user `homemovies-infrastructure` | Future Terraform workload identity |
| Group `homemovies-infrastructure` | Contains only that service user |
| Service user `homemovies-app-deploy` | Future application deployment identity |
| Group `homemovies-app-deployers` | Contains only that service user |
| Existing grocery GitHub trust | Add the Home Movies audience, non-admin client and two subject mappings |

The trust maps the exact environment subject
`repo:<repository>:environment:homemovies-infrastructure` to the infrastructure
service user and `repo:<repository>:environment:homemovies-production` to the
deployment service user. There is no single-branch restriction. Service users
have no passwords, email addresses or API signing keys. Oracle's
[service-user documentation](https://docs.oracle.com/en-us/iaas/Content/Identity/api-getstarted/kerberos_token_exchange.htm)
describes these non-interactive identities; the
[JWT exchange documentation](https://docs.oracle.com/en-us/iaas/Content/Identity/api-getstarted/json_web_token_exchange.htm)
describes the trust and impersonation mapping.

The workflow creates no OCI IAM policy, VM, network, bucket, secret or dynamic
group. Its one shared-trust PATCH contains only three additive operations:
one audience, one OAuth client and two service-user mappings. It preserves the
trust's name, issuer, JWKS URL, active state, original grocery audience/client
and original grocery mapping. There are no source-tenancy operations.

The protected bootstrap environment variable `OCI_WIF_SHARED_TRUST_NAME`
explicitly selects the existing trust. It is configured without putting its
actual identifier or service-user IDs in the public repository. Separate
project service users/groups continue to determine separate OCI IAM permissions;
the issuer trust is intentionally shared.

## Safety and retry behavior

Before writing, the helper reads the complete identity inventories and checks
all dedicated names, existing group membership and the selected shared
trust. A conflict stops the job. Groups are created with their single service
user already attached. Successful creation is followed by a fresh read-only
inventory verifying that the expected resources and memberships exist. A
shared-trust update uses `If-Match` with the inspected SCIM version, so a
concurrent change fails instead of being overwritten. The final read verifies
that all original grocery clients, audiences, mapping values and verification
controls remain intact. Server-added mapping metadata is preserved.

An interrupted request can leave partial creates. The helper does not retry
POST requests or delete partially created identities. Run the read-only plan
again before resuming: verified existing resources are reused; mismatches fail
for review. Logs contain aggregate results and sanitized failures, with no
service-user IDs, credentials or API response bodies in the helper's output.

## Owner checkpoint and execution

These steps are complete; do not re-enable the apply trigger for routine deployments.

1. Review this resource list and the branch files
   `scripts/oci_bootstrap_apply.py` and
   `.github/workflows/oci-federation-bootstrap-apply.yml`.
2. The owner has approved identity creation and reuse of the existing trust.
   No additional credentials or confidential applications are needed.
3. The agent will temporarily enable repository variable
   `ENABLE_HOME_MOVIES_BOOTSTRAP_APPLY=true` and push the migration branch to
   trigger its workflow. This flag is currently absent/disabled. The job still
   requires your approval in GitHub's **Review deployments** dialog for
   `homemovies-bootstrap` before the administrator secret is released.
4. Review the completed aggregate results. The agent will disable the one-time
   apply trigger immediately afterward, including on a failed attempt.

Permanent WIF verification stays disabled until the service-user OCIDs and
initial OCI IAM permissions have been configured. Creating a federation trust
does not grant workload permissions by itself.

## Next checkpoint: initial OCI IAM and Terraform plans

The next checkpoint will prepare and review the initial scoped OCI IAM grants
and Terraform state bootstrap, separately from this identity creation. It must
resolve the runtime dynamic group's tenancy scope before granting infrastructure
permissions. OCI's
[IAM policy reference](https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/iampolicyreference.htm)
states that target dynamic-group ID/name conditions are unavailable for creation
and listing. Consequently, the routine Terraform identity must not receive
tenancy-wide dynamic-group creation rights merely to create this VM's group.
The application module currently declares that resource; its ownership/bootstrap
will be reconciled before any real application Terraform plan or apply.

No permanent OCI API signing key will be uploaded to Actions. No DNS change,
B2 movie copy or public application deployment is part of this checkpoint.

Validation: 96 offline Python tests pass with 97.68% combined statement coverage.
Tests cover guarded execution, exact membership, conflicts before writes,
partial-success recovery, malformed responses, verification failure and
sanitized output, issuer collisions, additive shared-trust changes, concurrent
modification and preservation of existing grocery configuration. CI runs these
tests on every push and pull request.
