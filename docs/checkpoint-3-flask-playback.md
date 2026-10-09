# Checkpoint 3: authenticated Flask playback and SQLite tokens

This checkpoint records the state at that stage. For current architecture and
remaining work, see [the accepted architecture](oci-migration-proposal.md) and
[Checkpoint 9](checkpoint-9-mp4-and-library-transfer.md).

The migration branch now has one application media implementation: native B2.
`app.py` loads private runtime configuration, `service.py` handles authenticated
views, and `b2_repository.py` discovers HLS movies and reads small playlists.
There is no OCI Object Storage or Redis playback path in the branch application.
The existing production deployment and default branch remain unchanged.

## Implemented behavior

- Browser sessions expire two hours after login; shares expire after 48 hours.
  Each master and child playlist request checks its session or share in SQLite.
  A share is restricted to its exact catalog movie. Child playlist URLs preserve
  that authorization context. Invalid shares never fall back to session access.
- Flask rewrites media, key, initialization segment and subtitle references to
  movie-prefix B2 download URLs. Child playlists return to authenticated Flask
  routes. Video bytes bypass Flask. Unknown catalog entries, traversal and
  external references are rejected. Every response is private/no-store and uses
  `Referrer-Policy: no-referrer`.
- The runtime key remains private, read-only and bucket-restricted. The bucket's
  private status is refreshed before issuing download grants. B2 grant duration
  is bounded by remaining parent authorization, with a five-second safety margin;
  requests exceeding that latency budget fail closed.
- Catalog discovery preserves exact object names and refreshes after five minutes
  on the next request. Normal discovery excludes `_migration-test/` objects.
- SQLite stores token state only, with hashed token IDs and explicit expiry
  predicates on every lookup. Expiry works independently of physical cleanup.
  Startup and a one-minute background task purge expired rows. Incremental vacuum
  reclaims free pages, the database is capped at 32 MiB, and errors/full storage
  deny authentication. No backup/restore is needed.
- QR challenges last 15 minutes from creation. Approval does not extend expiry;
  browser-bound consumption is atomic and single-use. Login, QR approval, share
  creation and logout POSTs have CSRF protection. Passwords use Werkzeug hashes;
  cookies are HttpOnly/SameSite and Secure for production HTTPS origins.
- The container launches Gunicorn as a non-root user. Runtime configuration can
  come from a named OCI Vault secret using instance principal authentication.
  Terraform/IAM integration for that access remains a later checkpoint.

## Local browser checkpoint

The synthetic six-second H.264/AAC movie has a master playlist and child playlist.
It lives under a random `_migration-test/` prefix in the private B2 bucket. Its
local application instance discovers only that test prefix. It has no source
tenancy access and no home movie objects have been copied.

Open [the local synthetic demo](http://127.0.0.1:5055/demo), press Play, try seeking
or replaying, then try the Share Video button. `/demo` is a loopback-only fixture
launcher convenience: it is defined solely in `scripts/run_b2_browser_test.py`,
is absent from the production factory, and only operates with synthetic-prefix
configuration. Do not deploy that script.

The browser demonstrated playback to completion without a media error. The live
HTTP checks verify direct B2 segment delivery, Range CORS preflight for the local
origin, no CORS grant for an unrelated origin, guest share master/child requests,
and rejection of anonymous application playlist requests. The earlier live probe
also verified cross-movie and sibling-prefix denial and server-side token expiry.
All 52 offline tests pass, including SQLite expiry across restart, bounded
capacity/reclamation, atomic QR consumption and authorization on child playlists.
The Gunicorn production factory also passed a local startup/health smoke test.
Workflow YAML and the public-file privacy check pass. The CI workflow includes
the offline tests on every push and pull request and enforces at least 91%
statement coverage across every application Python module. Local coverage is
96.46%; runtime configuration/Vault tests use mocks and need no cloud credentials.
No GitHub workflow has been dispatched for this checkpoint.

The installed B2 CLI added only the exact `http://127.0.0.1:5055` download CORS
rule, preserving existing rules and the Private bucket setting. Its isolated
credential cache was removed. The Read and Write fixture-key preset includes
bucket-administration permission; never use it as the application's runtime key.
The private previous CORS rule list is in `.local/b2-cors-before.json`.
See [B2's private-bucket CORS documentation](https://www.backblaze.com/docs/cloud-storage-cross-origin-resource-sharing-rules).

Local credentials/settings are in ignored `.local/` files with owner-only file
permissions. Use `.local/browser-login.json` if testing the normal login page.
Do not paste these files into issues or include them in screenshots or artifacts.

To run again after preparing fixtures and installing application dependencies:

```sh
python scripts/run_b2_browser_test.py
python scripts/verify_b2_browser_routes.py
python -m pip install -r scripts/requirements-test.txt
python -m coverage run -m unittest discover -s scripts -p 'test_*.py'
python -m coverage report
```

To run the production factory locally, set `HM_CONFIG_FILE` to an owner-only
private JSON file and launch `python python_app/app.py`. Required keys are
`SECRET_KEY`, `PUBLIC_ORIGIN`, `USERNAME`, `PASSWORD_HASH`, `TOKEN_DB`,
`B2_BUCKET_ID`, `B2_APPLICATION_KEY_ID`, and `B2_APPLICATION_KEY`.
For OCI deployment, omit `HM_CONFIG_FILE` and set `HM_CONFIG_SECRET_OCID` to the
Vault secret containing that JSON. Use a persistent random session secret and
a writable token directory owned by container UID 10001.

## Remaining before production or movie transfer

This checkpoint covers HLS only. Standalone MP4/MOV/AVI delivery and the actual
source playlist inventory still need compatibility review; no objects will be
renamed or silently converted. Source transfer preserves every original key.
Real family-device testing, the exact production-origin CORS rule, deployment
via Terraform/Actions, Caddy/HTTPS and OCI Vault permissions remain pending.
Basic login throttling also remains before exposing the new application publicly.

A documentation checkpoint is scheduled after the deployment and upload paths
are tested, before cutover/merge. It will update all READMEs and operational docs
to the final architecture, replace obsolete instructions, and preserve/migrate
the encoding and manual upload runbook to native B2 without renaming files or
prefixes. See the [documentation and continuous-check checkpoints](automation-and-cutover-plan.md#documentation-checkpoint-before-cutover).

Synthetic fixtures and the local demo remain available for user review. After
acceptance, remove only the file versions recorded in the ignored fixture state
using `scripts/cleanup_b2_browser_test.py`, stop the local server, and retire the
temporary fixture key. The local CORS test rule can be removed when no longer
needed; do not remove production CORS rules.
