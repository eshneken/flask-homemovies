# Automation and cutover

Destination infrastructure and application releases run from GitHub Actions with
permanent OCI workload identity federation. Trusted repository branch pushes are
eligible, including future application pushes; pull requests and tags cannot deploy.
No GitHub reviewer gates are configured, by owner preference. The identity domain's
existing GitHub issuer trust is extended additively; grocery mappings remain intact.

## Implemented automation

| Workflow | Purpose | Environment |
|---|---|---|
| `public-files.yml` | Credential-free tests, coverage gate, privacy check, Terraform mock tests on every push/PR | None |
| `oci-wif-verify.yml` | Verify permanent OCI federation | Production and infrastructure |
| `oci-application-infra.yml` | Terraform application plan/apply with private native OCI state | `homemovies-infrastructure` |
| `oci-app-deploy.yml` | Native ARM64 tests/build, GHCR digest release, Run Command deployment and local VM health check | `homemovies-production` |
| `oci-federation-bootstrap-plan.yml`, `oci-federation-bootstrap-apply.yml`, `oci-infra-bootstrap.yml` | Initial identity/IAM/state/Vault bootstrap; disabled after setup | `homemovies-bootstrap` |

Enable flags and operation selectors are repository variables documented in the
checkpoint files. Infrastructure operation `plan` is read-only; `apply` uses its
saved plan. Existing workflows serialize infrastructure and release jobs. Manual
workflow dispatch becomes available when these workflows reach the default branch;
branch push triggers exercise the implementation beforehand.

## Infrastructure ownership

`infra/foundation/` owns the private versioned state bucket, standard Vault and
software key. `infra/iam-bootstrap/` owns automation permissions and initially seeds
the runtime dynamic group. `infra/application/` imports that group, narrows it to
one VM and owns networking, A1 VM, NLB, Bastion and runtime secret metadata. Real
secret content goes directly to Vault; Terraform retains an empty JSON placeholder
and ignores content changes. Bootstrap and application state are separate private
objects. Plans/state/identifiers are never public CI artifacts.

## Media migration and current pilot

Public DNS has been switched by the owner to the NLB for synthetic browser testing.
Caddy has a trusted Let's Encrypt certificate. HLS and MP4 public-path tests passed;
only the synthetic collection is selected through private runtime configuration.
The real library copy and verification are in progress; [Checkpoint 9](checkpoint-9-mp4-and-library-transfer.md)
records results and the temporary source helper.

The source helper is created with local Terraform and the existing source profile;
the source tenancy has no GitHub WIF configured for this project. It is an isolated,
temporary copy resource, not destination application infrastructure. Native OCI
instance-principal and native B2 rclone backends copy the original object names.
`copy` never deletes source or unrelated destination objects. Full streamed content
verification follows; five zero-byte folder markers are copied separately through
the native API. Keep transfer credentials/logs/inventories outside Git and GitHub.
Delete the helper and revoke its temporary B2 key after verification.

## Remaining acceptance before merge

1. Finish the library copy, full-content verification and exact name/size inventory
   comparison. Source objects and the running source app stay intact.
2. Remove the synthetic-only discovery setting, reload the application and verify
   all seven HLS collections and 30 standalone MP4 files through the public site.
3. Have the owner test real playback, seeking and sharing on family devices. Any
   codec incompatibility needs a separate decision; do not silently transcode files.
4. Confirm documentation and the manual B2 upload procedure match the implementation,
   CI passes, and no legacy source-deployment workflow remains on the branch.
5. Merge only after full cutover acceptance. Keep the existing source resources
   until the owner explicitly authorizes their retirement. The owner can restore
   the previous DNS record for a simple rollback while those resources remain.

No Redis/SQLite backup workflow, Kubernetes cluster, certificate PV, automated
monitoring program, or extra catalog/prefix/version system is required. Uploads
remain a manual operation using the [B2 runbook](manual-b2-upload.md).
