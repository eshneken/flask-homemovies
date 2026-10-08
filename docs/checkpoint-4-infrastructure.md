# Checkpoint 4 — destination infrastructure preparation

## Verified so far

Work remains on `codex/oci-a1-b2-migration`. The destination profile authenticated
successfully and its owner-created application compartment was found. A read-only
inventory of root/accessible compartments in the configured destination region
found one active A1 instance, 2 OCPUs, 12 GB RAM and 100 GB of boot/block volumes.
Home Movies adds 1 OCPU, 2 GB RAM and 50 GB: projected regional totals are 3 OCPUs,
14 GB RAM and 150 GB. This is an inventory, not a billing guarantee or an A1
capacity reservation; any additional regions/resources must be included before apply.

Actual identifiers and the inventory are stored only in ignored owner-readable
local files. The source application, source objects and grocery resources were
not changed. No new OCI resources have been created.

## Reviewable implementation

[Infrastructure modules and remaining apply gates](../infra/README.md) define the
private state/Vault foundation and a separate VCN with a private A1 application
subnet and a public NLB subnet. The VM has no public IP; outbound traffic uses
a managed NAT gateway. Caddy terminates TLS on the private VM.
IMDSv1 is explicitly disabled. Credential-free Terraform mock tests check the
reviewed storage/compute budget, loopback application binding and private state.
GitHub's existing branch-wide test workflow now includes Terraform formatting,
initialization, validation and mocks, alongside the application coverage gate.

This is the first part of the infrastructure checkpoint. Federation bootstrap, safe remote-state bootstrap and the image
build/Run Command submission workflows remain to be completed before provisioning.
The VM secret/agent policy, managed Bastion, token-exchange action and root-owned
deployment helper now have draft implementations and offline tests. Existing grocery WIF
provides a reference pattern; its repository-bound trust is not reused directly.

## Next validation

Review the dedicated-network boundary and the module inputs. Then establish the
Home Movies GitHub trust using the re-enabled identity-domain bootstrap authority,
validate the token exchange from the migration branch, and inspect the private
Terraform plan. Only after that checkpoint will the destination host be created.
No production DNS or default-branch change is part of this checkpoint.

## Maintenance access clarification

The initial infrastructure draft used one public subnet and a VM public address
with restricted ingress. That draft was corrected before provisioning: the VM
now belongs to a private application subnet and the NLB to a public load-balancer
subnet. Tests require the VM public-IP flag to be false and its subnet to prohibit
public IPs. OCI Bastion managed SSH, its agent plugin and private-endpoint-only
port 22 access are now implemented in Terraform; live validation remains required
after provisioning.

## Continued implementation

The destination default identity domain was discovered and read through the
existing local API profile. This was read-only; no trust or identity was created.
The existing trust remains grocery-specific. Dedicated Home Movies bootstrap
authority is still required for the initial GitHub-run identity setup.

Bastion uses the private application subnet, one operator IPv4 /32, and a
one-hour maximum session lifetime. The host permits only its private endpoint
on port 22. VM permissions use an exact-instance dynamic group, one named
secret-bundle grant and access to its own Run Command executions. Dynamic-group
creation has tenancy scope and will need explicitly limited bootstrap authority.

The VM helper accepts only the configured repository and an immutable digest,
pulls before changing the service, serializes deployments and checks local
health. Failures are sanitized. A failed health check reports failure; automated
rollback remains deferred as requested.

Offline CI coverage now includes the token-exchange and VM deployment helpers.
These tests do not constitute a live GitHub exchange, host deployment, certificate
issuance or IAM authorization test. No workflow has been pushed or dispatched.

## Permanent federation across branches

The authentication integration is permanent, including future app pushes. The
verification workflow now accepts every repository branch push once opted in.
The helper matches the JWT ref to the actual triggering branch and retains exact
repository ID, repository/environment subject, audience and expiry checks. PR and
tag contexts are rejected. Remove the staging environment's single-branch
restriction; its trust remains specific to this repository and environment.
This changes authentication eligibility, not the existing source deployment or
the requirement to review infrastructure plans before provisioning.

## Production environment naming and bootstrap preflight

The protected GitHub environment is `homemovies-production`, which will continue
to serve the application after migration. Workflow and documentation references
now use that name. The expected GitHub subject is
`repo:eshneken/flask-homemovies:environment:homemovies-production`; the trust must
match it exactly. The repository opt-in variable is now
`ENABLE_HOME_MOVIES_WIF`, with no staging-specific naming. Leave it unset until
trust and service identity setup are ready.

Read-only GitHub checks confirmed the runtime client secret is an environment
secret, not a plain variable, and the configured identity domain matches the
destination. The ignored bootstrap file is present with owner-only permissions.
Its administrator OAuth credentials successfully authenticated and read the trust
collection. The access token remained in process memory; no identities, trusts,
IAM policies, GitHub settings or workload resources were changed.
