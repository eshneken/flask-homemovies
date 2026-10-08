# Checkpoint 2: synthetic B2 integration validation

The existing app startup and deployment are unchanged. `python_app/b2_media.py`
contains independently tested primitives for later integration with authenticated
Flask routes. Child playlists stay on application routes; media objects, keys,
initialization segments and other dependencies receive B2 URLs. Source references
outside the movie prefix are rejected. Movie entrypoints must come from the
server's catalog. Runtime routes must enforce parent authorization on every
playlist request and return `Cache-Control: no-store` with referrer suppression.

## Temporary uploader

Create a separate standard B2 key restricted to the movie bucket with **Read and
Write** access and filename prefix `_migration-test/`. Leave **Allow List All
Bucket Names** unchecked. Store its bucket ID, application key ID and application
key in `.local/b2-upload-test.json`, using the same JSON structure as the playback
file. Set file permissions to 600. This key is for fixtures only and is not the
eventual movie migration/upload key.

```sh
.venv-b2/bin/python scripts/b2_live_probe.py \
  --playback-config .local/b2-preflight.json \
  --upload-config .local/b2-upload-test.json
```

The probe creates four tiny objects under a randomly generated `_migration-test/`
prefix. It checks anonymous rejection, an authorized movie download, exact Unicode
and space handling, Range requests, rejection for another movie and a similarly
named sibling prefix, and server enforcement of an expired two-second token.
It removes only the exact file versions uploaded by that run. Raw API errors,
credentials and bearer URLs are suppressed. An interrupted process may leave
synthetic objects; inspect only `_migration-test/` in that case.

The fixtures are synthetic bytes, not playable video. This test proves B2 access
boundaries; browser playback and CORS remain separate acceptance checks. CORS
requires the destination site's exact origin and bucket-admin access; the playback
key cannot change it. Do not broaden the playback key's privileges.

Run offline tests with:

```sh
.venv-b2/bin/python -m unittest discover -s scripts -p 'test_b2*.py'
```

Do not transfer home movies until live boundary checks and real browser HLS
playback pass. No OCI resource is changed by these tests.
