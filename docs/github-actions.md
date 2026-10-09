# GitHub Actions setup

GitHub Actions runs offline checks, provisions application infrastructure with
Terraform and publishes/deploys immutable ARM64 images. Repository workflows and
`.github/actions/setup-oci-wif/` define the implementation. Configure real values
in GitHub environments; never hardcode tenancy identifiers, DNS names, contact
addresses or credentials in these files.

## Workflows and execution locations

| Workflow file | Trigger and purpose | Cloud credentials |
| --- | --- | --- |
| `public-files.yml` | Every push and PR: public-file check, unit tests, >90% coverage, Terraform validation/mock tests | None |
| `oci-wif-verify.yml` | Enabled branch pushes/manual runs: verify the production federation identity | Short-lived OCI session via WIF |
| `oci-application-infra.yml` | Enabled branch pushes affecting infrastructure/helpers, or manual runs: Terraform plan/apply | Infrastructure WIF identity |
| `oci-app-deploy.yml` | Enabled branch pushes affecting app/helpers, or manual runs: ARM64 build, GHCR publish, VM deployment | GitHub job token for GHCR; deployment WIF identity for OCI |
| `oci-infra-bootstrap.yml` | Explicitly enabled initial setup: establish IAM/state/Vault foundation | Temporary operator bootstrap session; disable outside setup |

Terraform and builds run on GitHub-hosted runners. The image build runs on an
ARM64 runner and tests before publication. The release job submits an OCI Compute
Run Command; the agent on the private VM runs the restricted root deployment
helper. That helper pulls the approved digest, atomically records it, restarts
`home-movies.service` and checks loopback health. No SSH key is used by CI, and
neither movies nor runtime authentication settings pass through the runner.
Infrastructure and application jobs have separate concurrency groups; avoid
manually rebooting the VM while a release is running.

## 1. Prepare OCI identities and resources

Create the application compartment and select a region/Oracle Linux A1 platform
image. Initial setup must establish the private versioned state bucket, standard
Vault/software key and dedicated infrastructure/deployment identities and IAM.
These are the `foundation` and `iam-bootstrap` Terraform modules. Terraform uses
the supplied application compartment; it does not own or delete it.

Configure GitHub workload identity federation in the OCI identity domain with
issuer `https://token.actions.githubusercontent.com` and the chosen audience.
Use confidential OAuth client credentials authorized for OCI token exchange.
Map this repository's environment subjects to the appropriate service identities:

```text
repo:OWNER/REPOSITORY:environment:homemovies-infrastructure
repo:OWNER/REPOSITORY:environment:homemovies-production
```

Replace OWNER/REPOSITORY with your repository identity in OCI configuration.
Use separate infrastructure and deployment service users/groups. The infrastructure
identity manages this compartment's resources and the specific runtime dynamic
group; the deployment identity can read the target and submit/read its Run Command
executions. The VM runtime identity reads its Vault secret through an instance
principal. Do not grant the routine client identity-domain administrator authority.

A domain can share an existing GitHub issuer trust. Extend its mappings without
replacing another project's mappings. Bind trust to the expected repository,
environment and audience. WIF is environment-bound, not limited to one branch:
routine workflows accept repository branch pushes and branch manual runs, while
PR/tag contexts are rejected. Anyone authorized to push deployable code is trusted
with deployment capability; manage repository write access accordingly.

The runner requests a GitHub OIDC token with `id-token: write`, generates an
ephemeral signing key and exchanges the token through the OCI identity-domain
OAuth endpoint for an OCI security token. The non-admin OAuth client secret stays
in GitHub environment secrets. The temporary OCI token/key/configuration are
removed when the job finishes. No long-lived OCI API signing key belongs in CI.

## 2. Create GitHub environments and credentials

In **Settings → Environments**, create `homemovies-infrastructure` and
`homemovies-production`. Use **No restriction** for deployment branches/tags to
allow all repository branches; workflow checks still reject tag/PR deployments.
These environments currently have no required-reviewer gates.

Set these variables in **both** environments, with each environment's mapped
service-user identity:

| Variable | Meaning |
| --- | --- |
| `OCI_WIF_DOMAIN_URL` | Identity-domain base HTTPS URL |
| `OCI_WIF_CLIENT_ID` | Non-admin confidential application's client ID |
| `OCI_WIF_AUDIENCE` | Exact audience registered with the GitHub trust |
| `OCI_WIF_SERVICE_USER_OCID` | Service user mapped for this environment |
| `OCI_TENANCY_OCID`, `OCI_REGION` | Application tenancy and region |
| `OCI_COMPARTMENT_OCID` | Owner-created application compartment |

Add environment secrets `OCI_WIF_CLIENT_SECRET` and `OCI_PRIVATE_CONFIG_MASKS`.
The first is the confidential client secret. The second is a newline-separated
list of private configuration values to mask before jobs invoke tools. Include
actual identifiers, domain/hostnames, contact address, bucket names and operator
IP where applicable. Update masks when changing those values. Variables configure
jobs; they are not a safe place for passwords or keys. Do not add empty variables;
leave unused/disabled settings absent.

## 3. Configure infrastructure inputs

In `homemovies-infrastructure`, add:

| Variable | Meaning |
| --- | --- |
| `OCI_COMPARTMENT_NAME` | Exact owner-created compartment name |
| `OCI_DEPLOYMENT_GROUP_OCID` | Deployment IAM group used in the runtime policy |
| `OCI_STATE_BUCKET_NAME` | Private versioned state bucket |
| `OCI_AVAILABILITY_DOMAIN`, `OCI_IMAGE_OCID` | A1 placement and Oracle Linux image |
| `OCI_BASTION_CLIENT_CIDR` | Current operator public IPv4 `/32` |
| `APP_HOSTNAME`, `ACME_EMAIL` | Public DNS hostname and Let's Encrypt contact |

Private bootstrap metadata in the state bucket supplies the Vault, key and runtime
dynamic-group identifiers. Terraform application outputs are stored privately in
that bucket too. Do not upload raw plans, state or outputs as public Actions
artifacts. Terraform creates a dedicated VCN, private VM, public NLB, NAT and
Bastion. It creates only empty runtime-secret content; write the real application
JSON directly to OCI Vault using authorized operator access.

The one-time `homemovies-bootstrap` environment is used only to establish missing
IAM/foundation resources. Its workflow takes private bootstrap settings and a
short-lived operator session in environment secrets
`OCI_BOOTSTRAP_SETTINGS_JSON` and `OCI_IAM_BOOTSTRAP_AUTH_JSON`. Keep bootstrap
triggers disabled once the foundation exists. Routine jobs use WIF instead.
Federation trust editing is an identity-domain administrator setup task, not a
normal application release operation.

## 4. Enable checks, infrastructure and releases

Repository variables control opt-in workflows; unset flags leave jobs disabled:

| Repository variable | Value when enabled |
| --- | --- |
| `ENABLE_HOME_MOVIES_WIF` | `true` |
| `ENABLE_HOME_MOVIES_APPLICATION_INFRA` | `true` |
| `HOME_MOVIES_APPLICATION_OPERATION` | `plan` or `apply` |
| `ENABLE_HOME_MOVIES_IMAGE_BUILD` | `true` |
| `ENABLE_HOME_MOVIES_APP_DEPLOY` | `true` |

First verify WIF, then run infrastructure with operation `plan`. Review the
aggregate change counts and choose `apply` when ready. There is no per-run approval
gate; the selected operation persists for future matching pushes. VM deletion is
protected. Cloud-init is launch-only: changing its template provisions future
hosts correctly but does not replace or reconfigure an existing VM. See the
[operator guide](operators-guide.md) for host maintenance.

After infrastructure exists, add `OCI_INSTANCE_OCID` to `homemovies-production`.
Write the runtime JSON directly into the application's named OCI Vault secret:
login username/password hash, persistent session signing key, public origin,
SQLite container path and read-only B2 key/bucket ID. Do not add those settings as
GitHub secrets or Terraform variables. Update public DNS to the NLB and keep the
B2 bucket private with CORS for the exact public origin.

Enable image builds and deployments, then push an application change or run the
release workflow manually. GHCR publication uses the job's short-lived
`GITHUB_TOKEN`, with `packages: write`; the VM anonymously pulls the software-only
public image. The deployment input is a digest from this repository, never a
mutable `latest` tag or arbitrary registry. Runtime settings are reloaded on
application restart. A successful deployment checks local health; use browser
playback and sharing checks for end-to-end verification.

Workflow **Run workflow** buttons require the workflow to exist on the default
branch. While developing a workflow solely on a feature branch, use its matching
push trigger or rerun an existing run. After merging, select the desired branch
in the manual run menu. CI checks remain active on every push/PR regardless of
cloud opt-in flags. Unit tests use mocks and temporary SQLite files, not B2/OCI
credentials or GitHub secrets; `.coveragerc` requires at least 91% coverage.

## Inspect failures

Open **Actions**, select the workflow and failed step. The public logs show safe
results/aggregate counts; raw Terraform, SDK configuration and token details are
suppressed deliberately. A WIF failure usually concerns environment/audience,
client credentials or subject mapping. A plan failure can concern IAM, state or
an unsupported replacement. A release failure can concern the VM agent, image
pull or application health. Use [Bastion](vm-maintenance.md) and the
[operator guide](operators-guide.md) for private host diagnostics.

Do not fix a deployment failure by exposing the VM, weakening B2 privacy or
printing secrets in Actions. State is retained for retry; failed jobs do not
require regenerating identities by default.
