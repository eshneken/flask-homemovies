# Home Movies infrastructure checkpoint

These modules are a migration-branch draft. No resources have been applied.
The existing application and the grocery project's resources are outside these
modules. The destination compartment is supplied by Actions environment variables,
not created by Terraform.

- `foundation`: private versioned Terraform-state bucket, standard Vault, software AES key.
- `application`: dedicated VCN with private application and public load-balancer subnets, one A1 host (1 OCPU, 2 GB RAM, 50 GB boot), public TCP NLB, Caddy and a loopback-only application container.
- `tests`: credential-free provider mocks checking budget, IMDSv2, private state and network exposure.

Run `terraform fmt -check -recursive infra`, then run `init -backend=false`,
`validate` and `test` in each module. GitHub runs these checks on every push and PR.
Mocks validate planned configuration; they do not prove OCI deployment, Caddy
package installation, Run Command delivery or certificate issuance works.

## Deployment configuration

Actual values belong in protected GitHub Actions environments and ignored local
files. Supply `OCI_TENANCY_OCID`, `OCI_COMPARTMENT_OCID`, `OCI_COMPARTMENT_NAME`,
`OCI_REGION`, `OCI_AVAILABILITY_DOMAIN`, `OCI_IMAGE_OCID`,
`OCI_RUNTIME_SECRET_OCID`, `OCI_BASTION_CLIENT_CIDR`, `APP_IMAGE_REPOSITORY`,
`APP_HOSTNAME`, `ACME_EMAIL`, and `TF_STATE_BUCKET`.
Map them to the corresponding `TF_VAR_*` inputs. Select an Oracle Linux 9 A1
platform image with OCI Cloud Agent support; no generic image is silently selected.

The VM receives only the runtime secret's OCID. Runtime JSON must set `TOKEN_DB`
to `/var/lib/homemovies/tokens.sqlite`, matching the boot-volume directory mounted
into the unprivileged application container. The disposable database has no backup.
Secret contents are never Terraform inputs or secret-bundle data sources.

The VM has no public IP and its application subnet prohibits public IP assignment.
Its default outbound route uses a managed NAT gateway for B2, ACME, package updates
and image pulls. The NLB lives in a separate public subnet whose default route
uses the Internet gateway. Inbound VM NSG rules admit only the NLB on 80/443 and
its health probe on 8080. Port 22 admits only the Bastion private endpoint.
There is no permanently provisioned operator SSH key. Flask port 5000 binds only to host loopback. Caddy uses its
packaged systemd service and boot-volume storage at `/var/lib/caddy`, with no
additional block volume. The health listener forwards only `/health` and sets
the configured Host header so Flask's trusted-host checks still apply.
The Oracle Linux installation uses Caddy's official COPR package instructions,
with the EPEL 9 ARM64 repository selected explicitly; this still needs live VM
validation. [Caddy installation](https://caddyserver.com/docs/install),
[OCI VCN resolver](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/dns.htm).

## Gates before applying

The infrastructure modules do not yet create federation identities or runtime-secret
content. VM secret access is restricted to one named secret and an exact-instance
dynamic group. The root-owned deployment helper is installed by cloud-init and
accepts only the configured GHCR repository with a SHA-256 digest. The initial
host service remains stopped until an approved image digest is supplied. Complete
these pieces in the next part of the checkpoint before applying the application:

1. Create dedicated Home Movies service identities, trust mappings and narrowly
   scoped IAM policies. Grocery's repository-bound trust cannot authenticate a
   different repository. IAM identities/trust have tenancy/domain scope; workload
   resources and their policies remain isolated to the application compartment.
2. Implement the GitHub token-exchange action with masked output and credential
   cleanup, and separate infrastructure/app-deploy permissions. The local destination
   profile is for read-only discovery, not a signing key uploaded to Actions.
3. Implement state bootstrap and immediate migration to the native OCI backend.
   Never treat authentication failures as a missing bucket. Do not discard local
   bootstrap state if remote state migration fails.
4. Write the existing private B2/application settings directly to the named Vault
   secret outside Terraform state. Grant the VM access to that specific secret.
5. Finish the ARM64 image build/publish job and Run Command submission workflow.
   The installed root-owned helper is digest-restricted; there is no arbitrary sudo
   for `ocarun`. The GHCR application image must be anonymously pullable; it contains
   application software only, with no credentials, runtime settings or media.
   A private registry would require a separate runtime pull credential.
6. Validate the Terraform-managed Bastion and VM agent on the live destination.
   Its allowlist requires the operator IPv4 address as a /32 and sessions are capped
   at one hour. Managed sessions supply the operator public key on demand; private
   keys stay on the operator laptop. Keep Actions deployment on Run Command.
7. Validate a private Terraform plan against the destination before any apply.
   Do not publish plans, state, identifiers, DNS names or private inventories as
   public workflow artifacts.

Do not run `apply` on this draft. Caddy and the network will be tested on the new
host before DNS cutover. The complete documentation migration and manual B2
upload runbook review remain a separate pre-cutover checkpoint.

## Federation implementation

The dedicated `setup-oci-wif` action and verification workflow are now present,
but no GitHub configuration or cloud trust has been changed. The action runs only
on ephemeral GitHub-hosted runners, verifies the expected repository ID,
repository/environment subject, ref, audience and token expiry before exchange,
and requests a key-bound OCI UPST. OCI validates the GitHub JWT signature.
HTTPS redirects are rejected and raw HTTP/SDK error bodies stay out of logs.
The helper refuses to overwrite an existing OCI config. An `always()` cleanup
step removes its own temporary key/token/config; runner disposal covers abrupt
job cancellation. Terraform reads the temporary HOMEMOVIES profile through the
standard SDK config path, without altering local workstation credentials.

The `homemovies-production` GitHub environment permits repository branches without a
single-branch restriction. OCI trust must match the exact repository/environment
subject. The helper permits branch push/manual-dispatch events and requires the
JWT ref to match the triggering branch; it rejects PR and tag contexts. Helper checks
do not replace these server-side restrictions. Configure `OCI_WIF_DOMAIN_URL`,
`OCI_WIF_CLIENT_ID`, `OCI_WIF_AUDIENCE`, `OCI_WIF_SERVICE_USER_OCID`,
`OCI_TENANCY_OCID` and `OCI_REGION` as protected environment variables and
`OCI_WIF_CLIENT_SECRET` as an environment secret. Use a dedicated non-admin client.

A new workflow cannot be manually dispatched until it exists on the default
branch. For branch-only testing, the verification workflow supports an opted-in
push trigger: set repository variable `ENABLE_HOME_MOVIES_WIF=true` only after the
protected environment and trust are ready, then push a branch change.
The opt-in verification runs on every branch push. The workflow only authenticates and reads the destination namespace; it does not
apply Terraform. No opt-in or push has been performed yet.
