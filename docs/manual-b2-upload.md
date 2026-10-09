# Manually upload movies to Backblaze B2

Use this procedure from your own computer when adding movies once or twice a year. It uses Backblaze's native CLI, without S3, GitHub Actions, or an application deployment. Preserve filenames, capitalization, spaces, and the complete destination prefix exactly. No UUID directories, release directories, or renamed movie files are introduced.

The commands below use the documented B2 CLI 4.x syntax. The private B2 bucket and migrated application's automatic discovery are configured. Use a dedicated bucket-restricted upload key for this procedure. During the synthetic pilot, real-library discovery remains disabled until migration verification is complete.

## 1. Prepare the local folder and upload key

For the current flat HLS format, the local movie folder contains:

```text
Years in Review/
  Movies 2026.hls/
    output.m3u8
    output000.ts
    output001.ts
    ...
```

Keep the existing `output.m3u8` naming convention and relative segment references. Encode locally using the existing FFmpeg procedure if needed. Put only that movie's playback files in this folder; keep originals and unrelated files elsewhere.

Use the dedicated upload application key for the private movie bucket, not the Flask runtime key or account master key. It needs `listBuckets` for CLI authorization, `listFiles` and `writeFiles` for uploads, and `readFiles` for verification downloads. Scope it to the movie bucket; it needs no delete, public-sharing, bucket-administration, or key-management permission. Keep it in your password manager or retrieve it from its designated OCI Vault secret when needed. [CLI authorization requirements](https://b2-command-line-tool.readthedocs.io/en/v4.4.0/subcommands/account_authorize.html)

Install the CLI once, in an environment outside the movie folder:

```bash
python3 -m venv "$HOME/.venvs/home-movies-b2"
source "$HOME/.venvs/home-movies-b2/bin/activate"
python -m pip install 'b2>=4.4,<5'
b2 version
```

For subsequent uploads, run just the `source` command to activate that environment. Set restrictive permissions for the local credential cache, then authorize interactively:

```bash
umask 077
b2 account authorize
```

Enter the upload key ID and application key when prompted. Do not put the secret directly into a shell command or save it with these instructions. The CLI stores credentials in a local cache until cleared.

## 2. Set the local source and exact destination

Edit these three values for the movie you are uploading:

```bash
MOVIE_BUCKET='your-private-movies-bucket'
MOVIE_DIR='/absolute/path/to/Years in Review/Movies 2026.hls'
MOVIE_PREFIX='Years in Review/Movies 2026.hls/'
```

`MOVIE_DIR` identifies the local folder containing `output.m3u8`. `MOVIE_PREFIX` is the complete object-name prefix, with a trailing slash and without a leading slash. It can instead be `Another Collection.hls/`, or another existing layout: copy the actual name exactly rather than adapting it to the example.

Every command quotes the source path and B2 URL, so spaces remain part of the exact object name. Do not substitute `%20` in CLI object names; the playback application encodes URLs when serving them.

With the example values, local `output000.ts` becomes `Years in Review/Movies 2026.hls/output000.ts`. The local folder's own name is not automatically added again. You do not need to create a B2 folder first.

Confirm the playlist exists before continuing:

```bash
test -f "$MOVIE_DIR/output.m3u8"
```

If that command fails, correct the source path. Confirm that every file referenced by the playlist is present locally. If replacing an existing movie, arrange a quiet period with viewers and complete the upload before viewing resumes; replacement uses the same keys and prefix.

## 3. Check filename prefixes, then preview and upload

Before every upload, check the entire destination inventory plus the candidate
files. This prevents a new file or sidecar from extending an existing MP4 name;
B2's native download grants are prefix-based. Keep the inventory private.
From the repository directory, with the test dependencies installed:

```bash
mkdir -p .local
umask 077
b2 ls --recursive --json "b2://$MOVIE_BUCKET" > .local/upload-inventory.json
python scripts/check_mp4_prefixes.py \
  --existing .local/upload-inventory.json \
  --source "$MOVIE_DIR" --prefix "$MOVIE_PREFIX"
```

Proceed only when this prints PASS. Do not create objects such as
`Family Highlights 2026.mp4.notes` or `Family Highlights 2026.mp4/anything` while `Family Highlights 2026.mp4` exists.
Keep sidecars under a separate name. The application refuses to issue new grants
when a collision exists, but an already-issued B2 token remains valid until expiry.
Do not rename existing movies to fix a collision; resolve the conflicting new
candidate instead. Serialize uploads; do not run concurrent uploads from another
computer between the inventory check and completion.

## Preview and upload the movie files

Upload the movie's dependencies before its main playlist. The exclusion also skips macOS `.DS_Store` files:

```bash
b2 sync --dry-run \
  --exclude-regex '^output\.m3u8$|(^|.*/)\.DS_Store$' \
  "$MOVIE_DIR" "b2://$MOVIE_BUCKET/$MOVIE_PREFIX"
```

Read the preview and confirm the destination is the intended movie prefix. Then run the same command without `--dry-run`:

```bash
b2 sync \
  --exclude-regex '^output\.m3u8$|(^|.*/)\.DS_Store$' \
  "$MOVIE_DIR" "b2://$MOVIE_BUCKET/$MOVIE_PREFIX"
```

Wait for successful completion before proceeding. If interrupted, rerun this command to finish the transfer. Default sync leaves unrelated destination objects intact; do not add `--delete` or `--keep-days` to this procedure. [Native CLI directory uploads](https://www.backblaze.com/docs/cloud-storage-use-the-b2-sync-command-with-the-cli)

This procedure covers the current single-playlist layout. If a movie has child playlists, the bulk step uploads those with the dependencies; check that those uploads succeeded before publishing the main `output.m3u8`.

## 4. Upload the main playlist last

```bash
b2 file upload \
  --content-type application/vnd.apple.mpegurl \
  --cache-control 'private, no-store' \
  "$MOVIE_BUCKET" "$MOVIE_DIR/output.m3u8" \
  "${MOVIE_PREFIX}output.m3u8"
```

Uploading the main playlist last lets a newly added movie become discoverable after its dependencies are present. For an existing movie, its old playlist remains present while files are replaced; the agreed quiet period handles that case. [Native CLI file uploads](https://b2-command-line-tool.readthedocs.io/en/v4.4.0/subcommands/file_upload.html)

## 5. Verify the upload

List the exact destination prefix:

```bash
b2 ls --recursive --long "b2://$MOVIE_BUCKET/$MOVIE_PREFIX"
```

Check names, file sizes, and that `output.m3u8` and all referenced segments are present. In the B2 console, inspect a segment's metadata: TS segments should use `video/mp2t`. The CLI guesses MIME types for bulk-uploaded files; verify that this works correctly on your upload computer. A wrongly typed file can be uploaded again to its identical key with an explicit type, for example:

```bash
b2 file upload --content-type video/mp2t \
  "$MOVIE_BUCKET" "$MOVIE_DIR/output000.ts" \
  "${MOVIE_PREFIX}output000.ts"
```

MIME corrections for child playlists use `application/vnd.apple.mpegurl`. Keep the bucket private; verify playback through the application instead of making files public for testing.

## 6. Check the movie in the application

The migrated application discovers movies from B2 and caches that listing in memory for at most five minutes, refreshing on a subsequent library request. A completed `.hls/output.m3u8` identifies an HLS movie. Existing movie names/prefixes remain the trusted catalog lookup keys. There is no separately published catalog file or CI catalog job.

After upload, wait up to five minutes and reload the library. Open the movie, play it, and seek ahead. Confirm its navigation section and title are correct. No application rebuild, deployment, SQLite update, or manual cache-editing command is needed.

If the movie is missing, check the destination prefix and `.hls`/`output.m3u8` conventions first. If it appears but playback fails, check the playlist's relative references, segment presence, and MIME types. Do not rename paths to work around the problem.

## 7. Finish

Clear the CLI's local authorization and deactivate the environment:

```bash
b2 account clear
deactivate
```

Keep your local originals. Replacing files at the same keys creates older B2 versions; the bucket's provisioned lifecycle rules handle their retention. This runbook does not change those rules or delete destination objects.

## Standalone files

For a standalone MP4 compatible with family browsers, preserve its exact key.
Refresh the private inventory as in step 3 and run the same prefix checker with
`--source '/absolute/path/to/Years in Review/Family Highlights 2026.mp4' --prefix 'Years in Review/Family Highlights 2026.mp4'` before
uploading. A file source maps to that exact key; do not append a trailing slash.
Then upload:


```bash
b2 file upload --content-type video/mp4 \
  "$MOVIE_BUCKET" '/absolute/path/to/Years in Review/Family Highlights 2026.mp4' \
  'Years in Review/Family Highlights 2026.mp4'
```

Then follow the same listing, library-refresh, playback, and cleanup steps. Use the actual MIME type for other supported formats; a MOV or AVI extension alone does not establish browser compatibility. Preserve existing objects during migration even when their format needs further compatibility testing.
