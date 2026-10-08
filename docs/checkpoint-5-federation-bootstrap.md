# Checkpoint 5 — read-only GitHub federation bootstrap plan

The OAuth credentials and destination discovery checks have passed locally.
The read-only identity plan found two dedicated service users, two groups and one
Home Movies trust to create. No existing trust needs modification or deletion.
No cloud resources, policies, identities or GitHub settings were changed.

The new `oci-federation-bootstrap-plan.yml` workflow is implemented on the
migration branch. This checkpoint publishes it for GitHub verification; the
bootstrap environment requires account-owner approval before its job can start. It authenticates to the
identity-domain API and reads users, groups and trusts, then prints only aggregate
change counts. It creates nothing. The confidential application's administrator
role is required for this API; the runtime exchange client remains non-admin.

## Next steps for the account owner

1. In the repository's Settings > Environments, create `homemovies-bootstrap`.
   Configure yourself as a required reviewer, so the temporary administrator secret
   becomes available only after approval. If you are the sole reviewer, leave
   Prevent self-review unchecked. Keep deployment branches/tags unrestricted.
2. Add these environment variables:

   | Variable | Source |
   |---|---|
   | `OCI_WIF_DOMAIN_URL` | Same destination domain URL as `homemovies-production` |
   | `OCI_WIF_CLIENT_ID` | Same non-admin Home Movies client ID as production |
   | `OCI_WIF_AUDIENCE` | Same audience as production |
   | `OCI_BOOTSTRAP_CLIENT_ID` | Administrator client ID from the ignored bootstrap JSON |

3. Add environment secret `OCI_BOOTSTRAP_CLIENT_SECRET`, using the administrator
   client secret from the ignored bootstrap JSON. Do not put it in production.
   This is the point at which the earlier instruction to keep it out of GitHub
   changes: a separate reviewed bootstrap environment and read-only job now exist.
4. Under Settings > Secrets and variables > Actions > Variables, add repository
   variable `ENABLE_HOME_MOVIES_BOOTSTRAP_PLAN=true`. This enables the read-only
   branch push workflow. Leave `ENABLE_HOME_MOVIES_WIF` absent or false.
5. Tell the agent when ready. The migration branch will be published and its
   credential-free tests and read-only bootstrap plan run. Approve only the
   bootstrap-plan job. Review its aggregate change counts before any identity apply.

A new workflow cannot be manually dispatched before it exists on the default
branch. The opted-in push event enables branch testing without changing the
current production branch. After the one-time bootstrap, remove the bootstrap
opt-in/credential and deactivate the administrator application as appropriate;
the non-admin WIF application remains active for future branch pushes.

## Subsequent checkpoint

The proposed trust maps the exact `homemovies-production` GitHub environment
subject to an application-deploy service user and `homemovies-infrastructure` to
a separate infrastructure service user. The infrastructure environment has not
yet been requested or configured. Both can use the same non-admin OAuth client;
OCI IAM permissions belong to the mapped service identities.

Identity-domain administration does not by itself grant OCI workload permissions.
The actual identity/trust apply and initial OCI IAM policy bootstrap remain to be
implemented and reviewed. No API signing key will be uploaded to routine Actions.
The current plan job is not a replacement for the later Terraform resource plan.

Local validation: 80 Python tests passed with 97.47% combined statement coverage.
The new planner is covered by tests for incomplete inventories, conflicting
identities/trusts, environment mapping and sanitized failures.

The bootstrap environment variable/secret names and destination domain were
verified without printing values. The missing reviewer gate and read-only plan
repository opt-in were configured after the owner reported setup ready.
The permanent WIF verification remains disabled until the new trust exists.

## GitHub verification results

The migration branch was published with a GitHub noreply commit identity. Local
and remote `main` remained unchanged. The credential-free application/public-file
job passed in GitHub. After the owner approved its reviewer gate, the
[read-only federation bootstrap plan](https://github.com/eshneken/flask-homemovies/actions/runs/37847879178)
passed and reported two service users, two groups and one trust to create, with
zero trust modifications/deletions or IAM/workload changes.

The initial Terraform CI job exposed missing Linux provider package hashes in
the macOS-generated lockfiles. The follow-up adds authenticated OCI provider
hashes for Linux AMD64 and macOS ARM64; CI retains readonly lockfile validation.
The one-time bootstrap-plan push trigger is disabled after its successful run,
and permanent WIF verification remains disabled pending identity/trust setup.
No identity or workload resources have been created by this checkpoint.

The subsequent [identity-creation checkpoint](checkpoint-6-identity-creation.md)
now provides a disabled, separately reviewed apply workflow. Initial OCI IAM
permissions remain a later checkpoint.
