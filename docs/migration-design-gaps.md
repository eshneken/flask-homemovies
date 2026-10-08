# Remaining migration decisions and acceptance evidence

This review supplements the [architecture](oci-migration-proposal.md) and [automation/cutover plan](automation-and-cutover-plan.md). The migration branch currently contains design documents only. None of the proposed application, Terraform, or workflow behavior has been implemented or exercised against the tenancies. Recommendations below are proposed defaults, not evidence that those account configurations or tests already exist.

**Current scope:** the user has deferred items 4–7. Advanced DNS/certificate transition planning, rollback orchestration, operational monitoring/recovery programs, credential rotation, and extra instance-identity isolation are optional future work, not requirements or acceptance gates for the initial migration. Implement working infrastructure, authentication/token expiry, native B2 playback, manual uploads, and the agreed branch-first promotion. Basic DNS routing, Caddy HTTPS, required credentials, and IMDSv2-only VMs remain functional requirements.

## 1. Publishing movies after migration

The user uploads once or twice a year. Provide a [manual native-B2 CLI runbook](manual-b2-upload.md) resembling the existing OCI bulk-upload instructions. Use a separately restricted uploader credential from the operator's computer. Keep every filename and complete prefix exactly as supplied. Encode locally or on temporary paid compute, never on the small serving VM.

Bulk-upload dependencies to the exact intended movie prefix, then upload the main `output.m3u8` last. Replacements overwrite the same object keys during an agreed quiet period. Movie discovery uses a bounded in-memory B2 listing cache with a starting five-minute TTL, refreshed on library requests. Display only qualifying movie entries, not segments or directories lacking their main playlist. No versioned catalog, catalog pointer, renamed prefix, or CI upload/catalog-publication workflow is needed. SQLite remains token-only.

Preserve existing source keys during migration and later uploads. Validate requested movie names against the discovered catalog before issuing a prefix grant; never authorize an arbitrary browser-supplied prefix. Existing name-based bookmarks need no migration alias system. Deletion is a separate explicit operation; removing a movie from discovery does not revoke already-issued B2 URLs.

Acceptance: follow the manual runbook to add a movie, interrupt/resume the dependency upload, replace a movie at the same keys during a quiet period, and verify discovery after cache expiry. A new movie is not listed before its main playlist is uploaded.

## 2. Library formats and real device compatibility

The existing application and README support standalone files as well as HLS, including MP4/MOV/AVI. We have inspected repository code, not the actual bucket inventory. Inventory formats, codecs, maximum movie duration, byte-range playlists, subtitle/key dependencies, and object names before declaring the scope complete. MOV/AVI extensions do not guarantee browser-decodable content.

The native B2 endpoint returns 200 without Content-Range for a Range request encompassing the entire object, including `bytes=0-`; some clients require 206. [B2 native Range behavior](https://www.backblaze.com/apidocs/b2-download-file-by-name)

Preserve all existing filenames and prefixes. If a required standalone file fails native delivery or device decoding, record that compatibility issue and resolve it explicitly before cutover; converting or renaming media is not an automatic migration step. Existing working standalone MP4s can use the same native B2 authorization policy; their serving behavior needs explicit acceptance. Do not silently introduce an S3/proxy fallback that restores two delivery architectures.

Acceptance must include the actual family's browsers/receivers, seeking, long pause/resume, and a movie started near authorization expiry. Real device results are a cutover gate.

## 3. Playback deadlines and revocation expectations

The design mentions duration plus pause allowance, but browser sessions have an absolute two-hour deadline and derivative grants cannot outlive it. A viewer logging in 110 minutes ago has less than ten minutes remaining, regardless of the movie's length. Fix the user flow explicitly: require fresh authentication when insufficient authorization remains for the selected movie plus the chosen pause allowance, or clearly support reauthentication and resuming at the previous position. Never extend an expired parent implicitly.

Choose the pause allowance and maximum playback-grant duration using the inventory and device tests. Share links retain their 48-hour deadline; a playback grant does not automatically last 48 hours. Revoking a share blocks new grants immediately, but issued B2 download URLs remain usable until their own expiry. That delay must be an accepted product/security property. Do not promise immediate revocation or assume application-key rotation invalidates existing download tokens.

SQLite expiry enforcement and bounded cleanup are already specified. Loss of that disposable cache invalidates its outstanding token records; no backup, restore, or migration of cache contents is added.

## 4. Advanced DNS/certificate transition — deferred

Use stock Caddy automatic HTTPS and route the movie hostname to the NLB. Defer certificate preissuance, special DNS transition/reversion procedures, and a dedicated cutover workflow. Resolve actual DNS/ACME errors if they prevent the site from working.

## 5. Rollback orchestration — deferred

Perform a simple final copy, DNS switch, and functional check. Defer rollback rehearsals, reverse synchronization, observation windows, and automated rollback. The earlier requirement to test the migration branch before merging remains in scope.

## 6. Monitoring and operational programs — deferred

Do not add monitoring providers, alarms, notification channels, scheduled operational checks, patch/reboot automation, or recovery drills in the initial implementation. Basic deployment success checks remain. SQLite expiry cleanup remains application functionality explicitly requested by the user; it is not deferred monitoring.

## 7. Extra credential/identity hardening — deferred

Defer automated credential rotation, a separate host secret-fetch service, and additional container metadata isolation. Initially Flask retrieves its named Vault secrets through the VM instance principal using an IMDSv2-capable OCI SDK. IMDSv1 must remain disabled on both destination and temporary migration VMs, as required by the user's AGENTS.md instructions. Keep ordinary private-bucket credentials and functional authorization.

## 8. Cost evidence and object lifecycle configuration

The remaining CPU/RAM/disk allowances are an inventory gate already identified in the architecture. Record actual shared resources, retained disks, bootstrap/state storage, and required network services before apply. Confirm that a replacement operation cannot temporarily exceed the combined block allowance.

Choose B2 lifecycle rules precisely: expire superseded/hidden versions after a short retention period and cancel abandoned multipart uploads, while leaving current movie versions intact. Never set a current-file age rule that hides the live library. B2 retains older versions by default and bills them until deleted. An interrupted upload can be resumed manually at the same prefix; lifecycle cleanup is asynchronous. [B2 version lifecycle rules](https://www.backblaze.com/docs/en/cloud-storage-lifecycle-rules)

Check actual shared OCI allowance consumption and expected B2 bytes before provisioning. Cost/retention settings remain in scope; budget alarms and an ongoing billing-monitoring program are deferred with item 6.

## Recommended implementation order

Inventory the real library, implement the token store, uniform playlist adapter, cached library discovery, and branch CI, and validate native B2 playback and the manual upload runbook. Add infrastructure/WIF/bootstrap and deployment helpers, complete the source copy, and perform a simple functional cutover check. Merge into the current production default branch after actual cutover acceptance, as already agreed. Items 4–7 add no initial implementation work beyond the functional baseline stated above.
