# Checkpoint 9 — MP4 compatibility and library transfer

Status: MP4 implementation passes local tests; public deployment and synthetic
validation are in progress. The library copy has not started.

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

Local suite: 126 tests passed with 97.62% statement coverage. Tests cover MP4
classification, Unicode names, HLS-fragment exclusion, direct redirects, sharing,
expiry, anonymous denial, cross-movie denial, collision detection, collisions
appearing during grant issuance, upstream errors and parent revocation during I/O.
A six-second fast-start H.264/AAC synthetic MP4 uses only the existing restricted
`_migration-test/` key. No real movie objects have been uploaded.

Before copying the 12,061 source objects (217,956,271,191 bytes), confirm paid B2
capacity and a temporary bucket-restricted migration key in ignored local
configuration. Use native OCI Object Storage and native B2 rclone backends; no
S3 configuration. Copy, never sync or move, preserving every name and prefix.
Keep credentials out of Terraform, GitHub, command arguments and public logs.
Store detailed transfer logs privately. Verify object names/counts/sizes and
content before enabling the real catalog; native OCI MD5 and B2 SHA-1 are not
directly comparable. Do not treat matching sizes alone as content verification.
The source bucket and running source application remain intact.

Remove the synthetic-only discovery setting only after verification. Complete
the manual B2 upload runbook and full documentation migration before branch merge.
