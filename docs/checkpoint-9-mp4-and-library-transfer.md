# Checkpoint 9 — MP4 compatibility and library transfer

Status: the full library is copied, content-verified and enabled on the destination.
Public checks passed for all 37 original movies. All nine temporary source helper
resources were deleted. Owner real-device acceptance and final repository cleanup
remain before merge. The source application and default branch remain unchanged.

## MP4 playback

The catalog preserves standalone MP4 filenames, including spaces, Unicode and
uppercase extensions. MP4 fragments inside HLS collections remain excluded.
The existing movie and sharing pages select `video/mp4` for standalone movies
and use an authenticated application redirect to an expiring native B2 URL.
Video bytes and Range requests go directly to B2. HLS keeps the existing manifest
rewriting path. Both formats use the same SQLite login/share expiry checks.
An explicitly invalid share cannot fall back to a logged-in session.

Native B2 download authorization is prefix-based. For MP4, the prefix is the full
original filename. Before and after minting a token, the application lists that
exact prefix with the native API and requires exactly one current filename.
Any matching sibling, including a non-catalog object such as `movie.mp4.notes`,
causes playback to fail closed. The application also requires an exact object
name when constructing the MP4 URL. Missing files and listing failures expose
no download URL. Parent expiry is rechecked after remote calls.

This is not an exact-file restriction enforced by B2: a conflicting object
uploaded after a token is issued could be accessible until that token expires.
The migration and all future uploads must reject names extending an existing
MP4 filename. Do not add sidecars such as `movie.mp4.notes`; do not rename any
existing movie to work around a collision. The current source inventory has
zero MP4 prefix collisions. The manual upload runbook must enforce this invariant.

References: [B2 native download authorization](https://www.backblaze.com/apidocs/b2-get-download-authorization),
[B2 current-file listing](https://www.backblaze.com/apidocs/b2-list-file-names).

## Validation and next steps

Local suite: 129 tests passed with 97.63% statement coverage. Tests cover MP4
classification, Unicode names, HLS-fragment exclusion, direct redirects, sharing,
expiry, anonymous denial, cross-movie denial, collision detection, collisions
appearing during grant issuance, upstream errors and parent revocation during I/O.
The [ARM64 release and VM deployment](https://github.com/eshneken/flask-homemovies/actions/runs/37868794634)
passed. Public HTTPS probes passed HLS and MP4 playback paths, direct B2 Range
downloads, sharing and cross-movie/anonymous denials. A live synthetic MP4
filename-prefix collision was rejected and then deleted. A short-lived native B2
token downloaded successfully before expiry and was denied afterward.
A six-second fast-start H.264/AAC synthetic MP4 uses only the existing restricted
`_migration-test/` key. The real library has since been copied and verified.

The copy preserved all 12,061 objects (217,956,271,191 bytes), including five
zero-byte folder markers. Native OCI and native B2 rclone backends were used;
no source objects were deleted or changed. Full streamed content comparison
passed for all 12,056 regular files with zero differences and no unexpected
errors. Five known rclone directory-marker listing messages were classified
separately; native B2 checks verified all five marker names and zero-byte sizes.
A fresh inventory matched every source name and size and confirmed the bucket
remains private. Detailed names, logs and credentials remain in ignored files.

The destination Vault configuration now enables the full catalog while preserving
existing authentication and B2 credentials. The [release and VM deployment](https://github.com/eshneken/flask-homemovies/actions/runs/37869706498)
passed. Public HTTPS checks passed every original movie page, seven HLS and 30
MP4 direct B2 Range reads, production CORS and unauthenticated B2 denial.
These checks verify integration and bytes; the owner must still confirm actual
playback, seeking and incognito sharing on usual devices.

All nine temporary helper resources were destroyed successfully; the local
Terraform state is empty. The original source application and movie bucket remain
intact. Revoke only the temporary full-bucket B2 migration key after acceptance;
keep the restricted runtime playback key. Complete final documentation/script
cleanup after owner acceptance, before merging the branch.

## Source helper and exact inventory

The temporary copy helper runs in the source tenancy, where the owner explicitly
allows helper resources. A local Terraform module and private state under
`.local/source-helper/` create an isolated compartment, network, public helper
VM, and a dynamic group/policy with read-only access to the source movie bucket.
There are nine new resources and no existing-resource updates or deletions.
The helper uses 1 E4 OCPU, 8 GB RAM and a 50 GB boot volume; IMDSv1 is disabled.
SSH is restricted to the operator's IPv4 /32. This temporary source setup uses
the existing local source profile, while destination infrastructure and releases
continue through GitHub WIF. Source API private keys are not copied to the helper.
Its rclone OCI backend uses instance-principal authentication; its B2 key is in
a private file transferred over SSH, outside Terraform and GitHub.

The native OCI rclone file listing preserves the 12,056 file object names. Five
additional source objects are zero-byte folder markers ending in `/`; rclone
omits those as directory entries. All five were copied successfully through the
native B2 HTTP upload API, retaining their exact names and zero-byte payloads.
The SDK upload helper rejects trailing slashes, but the native API accepts them. Verify all 12,061 object names and sizes including those markers.
Use a streamed full-content check for the files, not a size-only acceptance.
Retain private results, remove the temporary helper resources after completion,
and revoke its temporary B2 key. The existing source objects remain intact.

The manual upload runbook now includes `scripts/check_mp4_prefixes.py`, which
checks the entire existing namespace together with candidate upload names before
any upload. It rejects non-catalog sidecars and directory keys extending an MP4
filename, without printing private object names.

The source helper's native instance-principal listing was compared by a canonical
name digest against all 12,056 file entries before transfer. The B2 migration key
was verified as restricted to the intended private bucket with no filename-prefix
limit and native read/write capabilities. The destination initially contained only
synthetic fixtures. `rclone copy --immutable --size-only` preserves completed files
when resumed; it does not delete source or unrelated destination objects. The job
then runs `rclone check --download --one-way` for full file-content comparison.
Do not enable the real catalog based only on copy completion or matching sizes.


## Operator documentation and restart checkpoint

The owner confirmed public synthetic MP4 playback, seeking and an incognito share
worked on the usual devices. README now contains architecture, HLS/MP4 playback
and sharing sequence diagrams, the real SQLite token schema, and explanations of
host Caddy, Podman/Gunicorn, embedded SQLite and boot-volume storage. Movie/upload
examples preserve spaces in `Years in Review/Movies 2026.hls/`.

[Operator guide](operators-guide.md) documents logs, paths, retention, recovery and
reboot checks. [Bastion instructions](vm-maintenance.md) include detailed console
steps and a CLI alternative. The current host and cloud-init template both use
Caddy crash recovery, unlimited application startup retries, stale-container
replacement, and persistent bounded journald retention. Updating instance metadata
does not rerun cloud-init on an existing host; the live host was explicitly updated
through a temporary Managed SSH maintenance session before validation.

A graceful destination VM reboot was tested. The boot ID changed; Caddy and the
application returned enabled/active without manual intervention. Public trusted
HTTPS retained the same certificate; a pre-reboot login and share remained valid.
Direct B2 Range reads for synthetic HLS and MP4 passed afterward. SQLite
`integrity_check` returned `ok`. This proves graceful reboot recovery; it is not
a forced power-loss or external-service-outage test.

## Final repository cleanup checkpoint

After the real library is verified and accepted, before merging the branch:

- Remove checkpoint/proposal/cutover/design-gap documents and temporary migration
  narratives. Rewrite README and retained guides to describe only the running app.
- Preserve the manual B2 upload procedure, operator guide, Bastion instructions,
  architecture diagrams, development/tests and generic Terraform/WIF setup.
- Retire synthetic fixture creation/browser-check/CORS setup scripts and their
  temporary credential requirements when those tests are no longer needed; keep
  credential-free unit tests and the permanent MP4 upload prefix checker.
- Remove one-time federation trust-patch/administrator bootstrap plan/apply
  workflows and helpers after moving any reusable new-tenancy setup guidance into
  permanent infrastructure documentation. Do not remove ongoing infrastructure,
  image release, WIF verification or credential-free test/coverage workflows.
- Remove the retired deployment directory and any other unused artifacts; update
  test imports/coverage configuration and all documentation links accordingly.
- Inventory references, rerun tests (>90% coverage), Terraform mock checks, privacy
  checks and live deployment verification after cleanup. Never remove a helper
  still required by a retained workflow or Terraform module.

This is the final cleanup step, not an additional architecture or monitoring
project. Source application resources and default-branch history remain untouched.

The infrastructure run initially rejected a cloud-init template change because
OCI's provider would replace the VM when `user_data` changes. The VM's existing
`prevent_destroy` protection blocked that action. Terraform now explicitly ignores
post-launch `metadata.user_data` changes; future VM creation uses the latest
template, while existing host changes require maintenance. No VM replacement was
performed.

Permanent [local development](local-development.md) and [GitHub Actions setup](github-actions.md)
guides replace README links to synthetic migration instructions. Final cleanup
must preserve both. Retain the generic IAM/foundation bootstrap capability needed
for a new tenancy; retire the extra one-off federation patch/plan/apply workflow
wrappers rather than deleting helpers still imported by normal infrastructure.
