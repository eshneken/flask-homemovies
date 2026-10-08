# Checkpoint 7 — initial IAM and durable Terraform state

Status: prepared for a read-only GitHub plan. No resources from this checkpoint
have been created yet. This checkpoint does not provision a VM, network, NLB,
Bastion, application secret or DNS record, and does not copy any movies.

## Resources and permissions to review

Terraform proposes five resources in the destination tenancy:

| Resource | Purpose and scope |
|---|---|
| Private versioned state bucket | Home Movies compartment; separate foundation, initial IAM and application state keys |
| Standard `DEFAULT` Vault | Home Movies compartment; no dedicated/HSM vault |
| Software AES-256 key | Home Movies compartment; `SOFTWARE` protection |
| Runtime dynamic group | Tenancy-level identity resource for this application only |
| Automation IAM policy | Tenancy-level policy granting the project identities the limited permissions below |

The infrastructure group can manage resources inside the Home Movies compartment,
read that compartment, inspect the Object Storage namespace, and manage the
**existing runtime dynamic-group ID only**. It cannot create unrelated dynamic
groups or change the tenancy-level automation policy. Compartment administration
includes this application's IAM policies and Vault secrets.

The application-deployment group can read instances and submit/read/cancel Run
Commands in Home Movies, plus inspect the namespace for authentication checks.
It cannot provision or delete a VM, edit networking, change federation, directly
read Vault secrets or access the Terraform state bucket. Deployment can run code
on this application's VM and thereby access its runtime secrets; protect the
deployment workflow and its GitHub environment accordingly.

These permissions do not grant access to grocery resources outside Home Movies.
The shared issuer trust remains as verified in Checkpoint 6; this job does not
change it. The original source application is outside all write paths.

## Runtime group ownership

OCI cannot scope dynamic-group creation by a target ID/name condition. The
one-time administrator job creates the group without granting that group any
OCI permissions. Its initial rule selects the application compartment, which
currently has no application VM. This is an intermediate bootstrap rule only.

After IAM apply, the job saves the group's ID in private bootstrap output
metadata, then removes only its Terraform state entry with `terraform state rm`.
This does not delete the OCI group. Initial IAM Terraform thereafter receives
the existing ID and does not recreate or manage the group. Application Terraform
imports it into its own state and replaces the rule with the exact VM ID **before**
creating the runtime policy that grants access to the one application secret and
its own agent executions. There is one Terraform owner after the handoff.

If execution stops between saving the metadata and forgetting the seed state
entry, a resumed apply compares the stored group ID before completing the
non-destructive handoff. The ordinary infrastructure identity can read/update
that specific group, but the condition cannot authorize group creation.

## Initial authority and GitHub configuration

The existing administrator OAuth client manages identity-domain resources. It
cannot grant OCI workload IAM authority by itself. The initial Terraform job
therefore uses a **one-hour OCI user session token**, bound to a newly generated
temporary RSA key. `scripts/oci_bootstrap_token.py` requests that token using the
local destination `EDFREETIER` profile. Its registered API key stays local and
is never uploaded. The script verifies destination identity and expiry, and
writes the temporary bundle to an ignored owner-only local file.

The protected `homemovies-bootstrap` GitHub environment holds temporary secrets
`OCI_IAM_BOOTSTRAP_AUTH_JSON` and `OCI_BOOTSTRAP_SETTINGS_JSON`. The latter is a
private configuration snapshot built from the configured GitHub compartment,
tenancy and region variables and the verified service-group IDs. The compartment
name/OCID, region and state bucket name remain environment variables; refresh
the snapshot before triggering a run if those variables change. Using the private
snapshot prevents GitHub from echoing raw infrastructure identifiers before the
helper can mask them. No API key or runtime B2/password secret is in the snapshot.

The helper accepts only a hosted runner in the protected environment, with an
explicit `plan` or `apply` operation on a branch. It requires at least 35 minutes
of token validity at entry; the GitHub job is bounded to 30 minutes. The owner
must approve promptly or a new session must be minted. The session and temporary
key can exercise the local administrator's authority during that hour, which is
why the job requires the existing reviewer gate and uses a reviewed branch.

Repo variable `ENABLE_HOME_MOVIES_INFRA_BOOTSTRAP` is a one-time opt-in.
`HOME_MOVIES_BOOTSTRAP_OPERATION=plan` performs no resource writes. The owner
reviews the aggregate counts and the permission list above before selecting
`apply`. Each new job still requires GitHub's deployment approval. Disable the
opt-in and delete the temporary session secret after each completed attempt.
The session mint helper refuses to overwrite an existing local bundle.

Routine foundation/application infrastructure jobs will use the permanent
Home Movies WIF infrastructure identity; routine app releases will use the
separate deployment identity. Neither receives this administrator bundle.

## State bootstrap, privacy and retry

The first apply creates only the state bucket using temporary local Terraform
state, saves that state immediately into the newly verified private bucket,
and initializes the native OCI backend before creating the Vault, key or IAM
resources. Subsequent operations use OCI backend state locking and a GitHub
infrastructure concurrency group. Foundation and IAM state use separate keys.
The native backend authenticates with the session profile; it contains no
private key/token values in its configuration.

Terraform output, plan JSON and state are not streamed to public job logs or
uploaded as GitHub artifacts. Plans stay in the ephemeral runner. The helper
prints only operation and create/update/delete/import counts. It rejects plans
with deletes/replacements. Private bootstrap output metadata contains resource
IDs, not application secret values, in the same private state bucket. The helper
checks the existing bucket's compartment, private access and versioning before
using it. Existing OCI state is authoritative on retries.

Credential files are owner-only and are removed at job exit, including failure.
The helper refuses to overwrite an existing OCI config. The local `~/.oci/config`
is never edited. The source `DEFAULT` profile is not used for token minting.

## Validation and remaining steps

Offline validation passes 106 Python tests with 97.49% statement coverage,
including the new session-bound bootstrap helpers. Terraform mock tests cover
separate deployment/infrastructure permissions and reuse of the transferred
runtime group. Existing tests continue to verify private VM placement, the
50 GB/1 OCPU budget and mandatory IMDSv2.

1. Run and approve the read-only bootstrap plan in GitHub.
2. Review counts and this permission/resource list; then run the separately
   approved apply operation with a fresh session if necessary.
3. Verify private bucket/Vault/key, scoped IAM grants and runtime group handoff.
   Configure the infrastructure environment from private bootstrap metadata.
4. Enable permanent WIF verification and test both mapped service identities.
   Remove temporary bootstrap credentials and disable its one-time triggers.
5. Prepare the actual application Terraform plan as the next checkpoint. It
   will import and narrow the runtime group, and create the private A1 VM/NLB
   architecture. No VM may be launched with IMDSv1 enabled.

References: [Oracle session authentication](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/clitoken.htm),
[Oracle Run Command permission reference](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/corepolicyreference.htm),
[OCI Terraform backend](https://developer.hashicorp.com/terraform/language/backend/oci).
