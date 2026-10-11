# Home Movies infrastructure

The application uses Terraform and GitHub workload identity federation. Supply
the owner-created application compartment name and OCID through GitHub
environment variables. These modules manage only this application.

- `foundation`: private versioned state bucket, standard Vault and software AES key;
  provisioned through the initial infrastructure bootstrap workflow.
- `iam-bootstrap`: separate infrastructure/deploy permissions and initial runtime
  dynamic group. Its group ownership is transferred to the application module.
- `application`: dedicated VCN, private A1 VM (1 OCPU, 2 GB RAM, 50 GB boot), public
  TCP NLB, NAT, Bastion, Caddy and a loopback application container. IMDSv1 is disabled.
  Terraform owns runtime secret metadata with an empty placeholder; real content
  goes directly into Vault and is never a Terraform input.

[GitHub Actions setup](../docs/github-actions.md) describes initial bootstrap,
ongoing Terraform plan/apply, and ARM64 image/Run Command deployment. Routine jobs
use WIF identities in `homemovies-infrastructure` or `homemovies-production`.
Temporary administrator bootstrap triggers remain disabled outside initial setup.

Configuration stays in ignored local files and GitHub environment variables:
`OCI_TENANCY_OCID`, `OCI_COMPARTMENT_OCID`, `OCI_COMPARTMENT_NAME`, `OCI_REGION`,
`OCI_DEPLOYMENT_GROUP_OCID`, `OCI_AVAILABILITY_DOMAIN`, `OCI_IMAGE_OCID`, `OCI_BASTION_CLIENT_CIDR`,
`OCI_STATE_BUCKET_NAME`, `APP_HOSTNAME`, `ACME_EMAIL`, and (for releases)
`OCI_INSTANCE_OCID`. Private bootstrap outputs identify the Vault/key/runtime group.
OAuth client secrets are environment secrets. B2/login settings never enter Actions.
Refresh `OCI_PRIVATE_CONFIG_MASKS` when environment variables change.

The VM has no public IP and permits only NLB web/health traffic and Bastion SSH.
Caddy persists certificates on the boot volume. The container is unprivileged and
binds Flask to loopback. Set runtime `TOKEN_DB=/var/lib/homemovies/tokens.sqlite`;
the directory is mounted from the boot volume and has no backup. Managed Bastion
sessions inject a public SSH key temporarily; private keys stay on the laptop.
The host accepts only immutable digests from the configured public GHCR repository.

GitHub runs tests on every push and PR. Locally, run `terraform fmt -check -recursive
infra`, then `terraform init -backend=false -lockfile=readonly`, `terraform validate`
and `terraform test` in each module. Mock tests require no cloud credentials and
verify budget, IMDSv2, private networking and secret placeholders. They do not prove
live image capacity, package installation, Run Command or certificate issuance.
