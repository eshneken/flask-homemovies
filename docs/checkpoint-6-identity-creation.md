# Checkpoint 6 — create dedicated federation identities

Status: implementation prepared; identity creation is disabled pending owner review.

The preceding read-only GitHub plan found two service users, two groups and one
trust to create. This checkpoint implements those writes through a separate
GitHub Actions workflow on the migration branch. It uses the existing protected
`homemovies-bootstrap` environment and its temporary administrator application.

## Review the exact changes

| Resource | Purpose |
|---|---|
| Service user `homemovies-infrastructure` | Future Terraform workload identity |
| Group `homemovies-infrastructure` | Contains only that service user |
| Service user `homemovies-app-deploy` | Future application deployment identity |
| Group `homemovies-app-deployers` | Contains only that service user |
| Trust `homemovies-github-actions` | GitHub issuer/JWKS, dedicated audience and non-admin OAuth client |

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
group. It does not update or delete existing resources. The grocery identities
and trust are outside its write paths. There are no source-tenancy operations.

## Safety and retry behavior

Before writing, the helper reads the complete identity inventories and checks
all dedicated names, existing group membership and any existing Home Movies
trust. A conflict stops the job. Groups are created with their single service
user already attached. Successful creation is followed by a fresh read-only
inventory verifying that the expected resources and memberships exist.

An interrupted request can leave partial creates. The helper does not retry
POST requests or delete partially created identities. Run the read-only plan
again before resuming: verified existing resources are reused; mismatches fail
for review. Logs contain aggregate results and sanitized failures, with no
service-user IDs, credentials or API response bodies in the helper's output.

## Owner checkpoint and execution

1. Review this resource list and the branch files
   `scripts/oci_bootstrap_apply.py` and
   `.github/workflows/oci-federation-bootstrap-apply.yml`.
2. Tell the agent to proceed with identity creation. No additional credentials
   or environment variables are needed for this step.
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

Validation: 88 offline Python tests pass with 97.49% combined statement coverage.
Tests cover guarded execution, exact membership, conflicts before writes,
partial-success recovery, malformed responses, verification failure and
sanitized output. CI runs these tests on every push and pull request.
