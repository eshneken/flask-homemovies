# Migration acceptance and deferred work

The [accepted architecture](oci-migration-proposal.md) and
[automation/cutover plan](automation-and-cutover-plan.md) describe the implemented
system. Checkpoints record chronological evidence; [Checkpoint 9](checkpoint-9-mp4-and-library-transfer.md)
tracks the current library transfer. This file lists remaining acceptance work.

- Complete the copy, streamed full-content check and exact-name/size inventory
  reconciliation, including the five zero-byte folder markers.
- Enable the real catalog and verify all seven HLS collections and 30 standalone
  MP4s. Test real playback, seeking and sharing on family devices; file extensions
  alone do not establish codec compatibility. Preserve original names and prefixes.
- Verify the manual native-B2 upload procedure, including the combined namespace
  check that rejects MP4 filename-prefix collisions. Uploads stay outside CI.
- Finish source-helper cleanup and owner revocation of the temporary B2 migration
  key. Keep detailed inventories and logs private.
- Keep the migration branch until full cutover acceptance. The old source app
  and source objects remain intact until the owner authorizes retirement.

The owner deferred advanced certificate-transition planning, automatic rollback,
monitoring/recovery programs, automated credential rotation and extra hardening.
They are not acceptance gates for this implementation. Functional private access,
expiry/cleanup, IMDSv2-only VMs, basic HTTPS and repository privacy remain required.
The disposable SQLite token cache requires no backup or restore process.
