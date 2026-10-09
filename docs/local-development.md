# Run Home Movies on your laptop

Run these commands from the repository root. Python 3.12 matches the application
image; no OCI VM, Caddy, Redis, OCI credentials or separate database server is
needed locally. SQLite comes with Python. Normal playback uses a private B2
bucket and a read-only native application key. Offline unit tests need neither
cloud credentials nor network access after installing dependencies.

## 1. Install dependencies

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r scripts/requirements-test.txt
umask 077
mkdir -p .local
```

Use `python3` instead if it is your Python 3.12 executable. Keep the virtual
environment outside `python_app/` so it cannot enter the application image.

## 2. Prepare B2 for local playback

Prefer a separate **private development bucket** containing a small HLS movie or
browser-compatible MP4. Use the [manual upload runbook](manual-b2-upload.md) to add
it with an upload key; run the app with a separate read-only key. An existing
private movie bucket also works, but the runtime key must never have write or
bucket-administration permissions.

Create a standard application key restricted to exactly that bucket. It needs
`listBuckets`, `listFiles`, `readFiles` and `shareFiles`; leave **Allow List All
Bucket Names** unchecked and leave the filename-prefix restriction empty. The
app verifies the single-bucket scope and refuses public buckets or write-enabled
keys. A directory filter in local settings can narrow discovery without granting
write access or changing existing object names.

For browser playback, add a CORS rule to this bucket alongside any existing
production rule. Use the B2 console if it supports custom rules, otherwise use the
native B2 CLI/API. Preserve existing rules when updating bucket configuration:

```json
{
  "corsRuleName": "home-movies-local-development",
  "allowedOrigins": ["http://127.0.0.1:5055"],
  "allowedOperations": ["b2_download_file_by_name"],
  "allowedHeaders": ["range"],
  "exposeHeaders": ["content-length", "content-range", "accept-ranges"],
  "maxAgeSeconds": 300
}
```

To configure this with the native CLI, install it as described in the upload
runbook and authorize interactively with a **bucket configuration key** that has
`listBuckets` and `writeBuckets`. The app's read-only key cannot change CORS.
Use this only for your selected development bucket. Capture its current rules
privately, append/update the named local rule and submit the complete list:

```bash
MOVIE_BUCKET='your-private-development-bucket'
umask 077
b2 account authorize
b2 bucket get "$MOVIE_BUCKET" > .local/dev-bucket-metadata.json
python - <<'PYCODE'
import json
from pathlib import Path
metadata = json.loads(Path('.local/dev-bucket-metadata.json').read_text())
assert metadata['bucketType'] == 'allPrivate'
rules = metadata['corsRules']
assert isinstance(rules, list)
rule = {
    'corsRuleName': 'home-movies-local-development',
    'allowedOrigins': ['http://127.0.0.1:5055'],
    'allowedOperations': ['b2_download_file_by_name'],
    'allowedHeaders': ['range'],
    'exposeHeaders': ['content-length', 'content-range', 'accept-ranges'],
    'maxAgeSeconds': 300,
}
rules = [item for item in rules if item['corsRuleName'] != rule['corsRuleName']]
rules.append(rule)
Path('.local/dev-cors-rules.json').write_text(json.dumps(rules))
PYCODE
b2 bucket update --cors-rules "$(cat .local/dev-cors-rules.json)" "$MOVIE_BUCKET" allPrivate
b2 account clear
```

Stop on any error; do not continue with an empty rules file. This retains existing
rules and changes only the named local rule. Revoke the temporary configuration
key afterward if it was created for this setup. Do not change the production
bucket merely to test a new local setup.

Keep the bucket private. CORS only lets the browser read authorized responses;
requests still require the temporary B2 token that Flask issues. See
[Backblaze CORS rules](https://www.backblaze.com/docs/cloud-storage-cross-origin-resource-sharing-rules).

## 3. Create private local settings

The following interactive command prompts for a local login and B2 credentials,
hashes the password, generates a session signing secret and writes an ignored
owner-only file. It does not contact B2 or upload anything:

```bash
python - <<'PY'
import getpass, json, os, secrets
from pathlib import Path
from werkzeug.security import generate_password_hash
os.umask(0o077)
root = Path.cwd()
settings = {
    'USERNAME': input('Local login username: '),
    'PASSWORD_HASH': generate_password_hash(getpass.getpass('Local login password: ')),
    'SECRET_KEY': secrets.token_urlsafe(48),
    'PUBLIC_ORIGIN': 'http://127.0.0.1:5055',
    'TOKEN_DB': str(root / '.local/dev-tokens.sqlite'),
    'B2_BUCKET_ID': input('Private B2 bucket ID: '),
    'B2_APPLICATION_KEY_ID': input('Read-only B2 application key ID: '),
    'B2_APPLICATION_KEY': getpass.getpass('Read-only B2 application key: '),
}
prefix = input('Optional exact discovery folder prefix, or Enter for entire bucket: ')
if prefix:
    settings['TEST_DISCOVERY_PREFIX'] = prefix
path = root / '.local/dev-app.json'
path.write_text(json.dumps(settings))
path.chmod(0o600)
print('Private local settings saved.')
PY
```

For the example movie `Years in Review/Movies 2026.hls/output.m3u8`, the optional
folder filter can be `Years in Review/`. Preserve spaces and capitalization; do
not enter URL-escaped `%20` names. The `TEST_DISCOVERY_PREFIX` setting is optional
local catalog filtering, not a replacement for B2 authorization. The runtime
key's bucket scope is still checked. Use a separate local login password rather
than copying production authentication settings.

Keep `SECRET_KEY` stable across restarts if you want existing local sessions to
remain valid. Never commit this file, the token database or private keys. Do not
copy credentials into command arguments or terminal recordings.

## 4. Start Flask locally

From the repository root, with the virtual environment active:

```bash
export HM_CONFIG_FILE="$PWD/.local/dev-app.json"
cd python_app
python -m flask --app 'app:create_runtime_app()' run \
  --host 127.0.0.1 --port 5055 --no-debugger --no-reload
```

Open **http://127.0.0.1:5055** and sign in with your local login. Use that exact
address; `localhost` does not match the configured trusted host and CORS origin.
The app fetches the catalog from B2, stores tokens locally, rewrites HLS playlists
and sends media downloads directly to B2. No production Vault secret is read when
`HM_CONFIG_FILE` is set.

Check playback, seeking and a Share Video link in a private window on the same
laptop. Loopback share/QR links cannot be opened from another device. Production
uses HTTPS with Secure cookies; this one loopback HTTP origin is the explicitly
allowed local exception. Do not bind the development server to `0.0.0.0` or expose
it publicly. Ctrl-C stops the server. Restart it after code/configuration edits
because this command intentionally disables automatic reload and the debugger.

If you want to run the same WSGI server used in the container, replace the Flask
command with:

```bash
gunicorn --bind 127.0.0.1:5055 --workers 1 --threads 4 --timeout 60 \
  'app:create_runtime_app()'
```

Gunicorn runs on macOS/Linux; use Flask's local server on Windows. If port 5055 is
already in use, stop the other local server or choose another port and update
`PUBLIC_ORIGIN`, the startup command and the bucket's local CORS origin together.
No SQLite process needs starting. Its file remains in `.local/dev-tokens.sqlite`.
For VS Code, copy `launch.json.sample` into ignored `.vscode/launch.json` and select
your virtual environment's Python interpreter. The sample runs `python_app/app.py`
on the same loopback port with `.local/dev-app.json`; stop any CLI server first.

## 5. Run tests and inspect coverage

From the repository root, in the active virtual environment:

```bash
python -m coverage run -m unittest discover -s scripts -p 'test_*.py'
python -m coverage report
python -m coverage html
python scripts/check_public_files.py
```

Open `htmlcov/index.html` for line-by-line coverage. Tests use mocked B2/OCI
clients and temporary databases; they do not read your development configuration
or require GitHub Actions secrets. The coverage threshold is 91%, ensuring it
exceeds 90%. These tests run on every GitHub push and pull request too.

Offline tests cover request authorization, token expiry/cleanup, catalog discovery,
HLS rewriting, MP4 prefix collisions and deployment helpers. They do not prove
browser codec compatibility or live CORS; use the local browser checks above for
those. See [GitHub Actions setup](github-actions.md) for CI and releases.

## Troubleshooting and cleanup

- Startup failure: check the private settings file is mode 600, credentials cover
  exactly one private bucket, and the key has the required read/share capabilities.
  Initialization deliberately suppresses raw SDK errors that can expose secrets.
- Login failure: use the local username/password entered during setup. Resetting
  the file's signing secret invalidates existing cookies.
- Empty library: check the optional discovery prefix and the `.hls/output.m3u8`
  or standalone `.mp4` naming convention. Listing refreshes after at most five
  minutes on a subsequent library request.
- Browser CORS error: check the exact loopback origin and Range header rule;
  keep production rules intact. Do not make the bucket public.

After stopping the app, deactivate the environment and unset its configuration:

```bash
unset HM_CONFIG_FILE
deactivate
```

You may remove the disposable development token database while the app is stopped;
local logins, shares and QR tokens will be invalidated. Keep credentials outside
Git and clear any separately authorized B2 CLI session after uploading.
