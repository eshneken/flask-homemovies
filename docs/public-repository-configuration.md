# Configuration for the public repository

The target compartment is created by the account owner before infrastructure bootstrap. Supply its name and OCID through GitHub Actions environment variables. Terraform references the supplied compartment; it does not create, import, rename, or destroy it. No destination tenancy identifiers or actual compartment names are hardcoded in repository files.

Configure these under the GitHub deployment environment's **Environment variables**:

| Variable | Value supplied outside Git |
|---|---|
| `OCI_COMPARTMENT_NAME` | Name of the compartment created by the account owner |
| `OCI_COMPARTMENT_OCID` | Its actual compartment OCID; required authoritative Terraform input |
| `OCI_TENANCY_OCID` | Destination tenancy OCID |
| `OCI_REGION` | Destination home region |
| `OCI_AVAILABILITY_DOMAIN`, `OCI_IMAGE_OCID` | Reviewed A1 placement and Oracle Linux 9 platform image; VCN/subnet are created separately for this application |
| `OCI_RUNTIME_SECRET_OCID` | One named runtime JSON secret containing the application and B2 settings |
| `APP_HOSTNAME`, `ACME_EMAIL` | Hostname for the deployment being tested and certificate contact |
| `OCI_BASTION_CLIENT_CIDR` | Operator public IPv4 address as a /32; stored outside Git |
| `APP_IMAGE_REPOSITORY` | Dedicated GHCR application repository, without tag or digest |
| `TF_STATE_BUCKET` | Dedicated private Terraform-state bucket name |
| `OCI_WIF_DOMAIN_URL`, `OCI_WIF_CLIENT_ID`, `OCI_WIF_AUDIENCE`, `OCI_WIF_SERVICE_USER_OCID` | Dedicated workload-identity configuration for that environment |
| `B2_BUCKET_NAME`, `B2_BUCKET_ID` | Private movie-bucket configuration |

Source migration uses corresponding source-tenancy environment configuration, separately from the destination. Keep actual bucket inventories, personal movie titles, verification reports, Terraform state/plans, local credential files, and generated certificates out of Git and public Actions artifacts.

Jobs must declare their GitHub environment to consume environment-level `vars`. The new Terraform workflow maps the compartment through runner environment variables rather than inserting its value into shell command text:

```yaml
jobs:
  infrastructure:
    environment: homemovies-production
    runs-on: ubuntu-latest
    env:
      TF_VAR_compartment_ocid: ${{ vars.OCI_COMPARTMENT_OCID }}
      TF_VAR_compartment_name: ${{ vars.OCI_COMPARTMENT_NAME }}
    steps:
      # Checkout and OCI workload-identity setup precede this step.
      - name: Validate required configuration
        shell: bash
        run: |
          if [ -z "$TF_VAR_compartment_ocid" ]; then
            echo 'OCI_COMPARTMENT_OCID must be configured for this environment.' >&2
            exit 1
          fi
      # Terraform consumes TF_VAR_* automatically; do not echo their values.
```

The snippet is a configuration contract for the migration implementation, not an executable infrastructure workflow already present. Use the same externally supplied compartment OCID for staging and production on the single destination VM. A name alone is not used to guess a compartment or silently create one. [GitHub environment variables](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables)

Credentials such as WIF client secrets and provisioning keys remain GitHub environment **secrets**; application credentials remain in OCI Vault. Actions variables are configuration, not secret storage. Avoid logging their values; mask identifiers before commands that could expose them and keep Terraform plan/apply output containing actual identifiers out of public logs/artifacts. Deployment helpers report status without dumping OCI API responses, secret bundles, or generated token URLs.

## Local checks and findings

Run `python3 scripts/check_public_files.py` before publishing changes. The read-only `public-files.yml` workflow runs the same check without cloud credentials. It reports filenames, line numbers, and categories, never matched values. This is a small guard for obvious credentials, OCI identifiers, personal paths/emails, and private artifact filenames; it is not proof that every possible type of PII or credential has been detected.

The review inspected tracked files, pending migration documents, the illustrative folder-structure image, and 91 unique blobs reachable through the local clone's 59 commits. It found a literal compartment OCID in `launch.json.sample` and an incidental personal organization label in the deprecated certificate-generation script. Those are sanitized on the migration branch. No private-key blocks or obvious access-token/password literals were identified by the targeted pattern checks. The image contains a generic example folder layout.

Historical versions still contain the compartment OCID. Git commit metadata also contains author/committer email addresses. Existing public repository links and the GitHub account identity are intentionally public references. Branch changes do not remove older commits or cached/forked copies. The initial requirement to preserve the original production branch remains in force: history has not been rewritten or force-pushed. Purging history is a separate coordinated operation because it changes commit IDs and affects other clones. The local audit did not inspect GitHub Actions logs/artifacts, PR-only refs, forks, cached pages, or live cloud resources. [GitHub historical-data removal](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

For future commits, configure Git locally to use the GitHub-provided noreply address if personal email disclosure is unwanted. Keep actual author email settings out of repository files. The public-file check inspects contents, not commit author metadata.

The federation verification workflow uses `homemovies-production`, with no
single-branch restriction. Its all-branch push trigger requires repository
variable `ENABLE_HOME_MOVIES_WIF=true`; leave it absent until trust and environment
configuration are ready. The runtime exchange credential is environment secret
`OCI_WIF_CLIENT_SECRET`. Initial identity-domain bootstrap authentication is
separate; never upload the local OCI profile/signing key to routine workflows.

WIF is the permanent authentication method for future infrastructure and app
workflows. The staging environment uses **No restriction** under deployment
branches/tags; the workflow/helper accept branch pushes and manual dispatches,
not PR or tag contexts. Authentication is repository/environment-bound, with
permissions determined by the mapped service identity. Production deployment
triggers and separate infrastructure/app permissions are configured independently
of WIF authentication. Existing source/default-branch deployment stays unchanged
until cutover.
