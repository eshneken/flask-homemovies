# Runtime configuration in OCI Vault

The application reads one JSON secret, `home-movies-runtime`, from OCI Vault at
startup. Terraform creates its metadata and an empty `{}` placeholder; an operator
populates the real content directly. Terraform ignores content changes and
protects the secret from deletion. The VM's instance principal can read only this
runtime secret. The image builder does not need its content, and it never belongs
in GitHub variables/secrets, Terraform inputs/state, container images or public logs.

## Values and examples

This is an illustrative complete production configuration. Replace every
placeholder before publishing it; the password hash and signing key below are
not usable credentials:

```json
{
  "USERNAME": "<site login username>",
  "PASSWORD_HASH": "<Werkzeug-generated password hash>",
  "SECRET_KEY": "<persistent random signing key>",
  "PUBLIC_ORIGIN": "https://movies.example.com",
  "TOKEN_DB": "/var/lib/homemovies/tokens.sqlite",
  "B2_BUCKET_ID": "<private bucket ID>",
  "B2_APPLICATION_KEY_ID": "<restricted playback application key ID>",
  "B2_APPLICATION_KEY": "<restricted playback application key>"
}
```

| Field | Purpose and update considerations |
| --- | --- |
| `USERNAME` | Shared site login. Change together with the password hash when replacing login credentials. |
| `PASSWORD_HASH` | Werkzeug hash of the login password, generated below. Never put a plaintext password here. Changing this affects new logins; existing authentication/share tokens retain their normal expiry. |
| `SECRET_KEY` | Flask session-cookie signing key. Generate once and keep stable across deployments. Rotating it invalidates existing signed session cookies, but does not delete independently stored share/QR tokens. |
| `PUBLIC_ORIGIN` | Exact HTTPS origin, without a trailing slash. It determines trusted host and generated links. A hostname change also needs DNS, GitHub `APP_HOSTNAME`, Caddy configuration and B2 CORS updates; an existing VM requires explicit Caddy maintenance because cloud-init runs only at creation. |
| `TOKEN_DB` | Path inside the container. Keep the shown production value; it maps to the boot-volume token directory. A different path needs a matching container volume configuration and can invalidate existing tokens. |
| `B2_BUCKET_ID` | Private bucket identifier. A bucket change also requires a matching restricted key, existing movie files and CORS for `PUBLIC_ORIGIN`. |
| `B2_APPLICATION_KEY_ID`, `B2_APPLICATION_KEY` | Native B2 playback key pair. Scope to exactly this private bucket, without a filename restriction, and capabilities `listBuckets`, `listFiles`, `readFiles`, `shareFiles`. No upload/delete capabilities. Rotate the pair together. |

Optional `CATALOG_PREFIX` filters discovery to an exact folder prefix such as
`Years in Review/`. Omit it to discover the entire bucket. It is a catalog filter,
not a B2 authorization boundary. No movie names or prefixes are rewritten.

Certificates stay in Caddy's boot-volume directory. Login/share/QR token rows stay
in SQLite. Neither certificates, token rows nor movies are stored in this secret.

## 1. Prepare a private complete JSON file

Use a local virtual environment with the dependencies in
`scripts/requirements-test.txt`; see [local development](local-development.md).
From the repository root:

```bash
mkdir -p .local
chmod 700 .local
python - <<'PY'
import getpass, json, os, secrets
from pathlib import Path
from werkzeug.security import generate_password_hash
os.umask(0o077)
path = Path('.local/runtime-app.json')
if path.exists():
    raise SystemExit('File already exists; use the update procedure instead.')
settings = {
    'USERNAME': input('Site username: '),
    'PASSWORD_HASH': generate_password_hash(getpass.getpass('Site password: ')),
    'SECRET_KEY': secrets.token_urlsafe(48),
    'PUBLIC_ORIGIN': input('Public HTTPS origin, without trailing slash: '),
    'TOKEN_DB': '/var/lib/homemovies/tokens.sqlite',
    'B2_BUCKET_ID': input('Private B2 bucket ID: '),
    'B2_APPLICATION_KEY_ID': getpass.getpass('Playback key ID: '),
    'B2_APPLICATION_KEY': getpass.getpass('Playback application key: '),
}
path.write_text(json.dumps(settings, indent=2) + '\n')
path.chmod(0o600)
print('Private configuration saved; no secret values printed.')
PY
```

Use the existing B2 playback key for normal configuration updates. Upload keys
are separate and must not replace the read-only runtime key. Keep the local file
outside Git, with mode 600; `.local/` is ignored. Never paste its contents into
GitHub issues, Actions inputs or chat.

## 2. Publish a version directly to Vault

Use an authorized local OCI profile with permission to update this secret.
Provisioning uses the destination tenancy; choose its profile explicitly rather
than relying on `DEFAULT`. Set the profile and runtime secret OCID privately in
your shell (the OCID is the application's Terraform `runtime_secret_ocid` output):

```bash
read -r -p 'Destination OCI profile: ' OCI_PROFILE
read -r -p 'Runtime secret OCID: ' HM_RUNTIME_SECRET_OCID
export OCI_PROFILE HM_RUNTIME_SECRET_OCID
```

The prompts above use Bash. On zsh, use these instead:

```zsh
read 'OCI_PROFILE?Destination OCI profile: '
read 'HM_RUNTIME_SECRET_OCID?Runtime secret OCID: '
export OCI_PROFILE HM_RUNTIME_SECRET_OCID
```

The following Python command works from either shell. It publishes a new CURRENT
version, then waits for that exact content to become readable. It prints only a
success/failure message:

```bash
python - <<'PY'
import base64, json, logging, os, time
from pathlib import Path
import oci
logging.disable(logging.CRITICAL)
try:
    path = Path('.local/runtime-app.json')
    if path.stat().st_mode & 0o077:
        raise ValueError('Owner-only file required')
    settings = json.loads(path.read_text())
    required = {'USERNAME', 'PASSWORD_HASH', 'SECRET_KEY', 'PUBLIC_ORIGIN',
                'TOKEN_DB', 'B2_BUCKET_ID', 'B2_APPLICATION_KEY_ID', 'B2_APPLICATION_KEY'}
    if not required <= settings.keys() or any(
        not isinstance(settings[k], str) or not settings[k] or settings[k].startswith('<')
        for k in required
    ):
        raise ValueError('Complete real configuration required')
    config = oci.config.from_file(profile_name=os.environ['OCI_PROFILE'])
    secret_id = os.environ['HM_RUNTIME_SECRET_OCID']
    vault = oci.vault.VaultsClient(config)
    reader = oci.secrets.SecretsClient(config)
    content = base64.b64encode(json.dumps(settings).encode()).decode()
    vault.update_secret(secret_id, oci.vault.models.UpdateSecretDetails(
        secret_content=oci.vault.models.Base64SecretContentDetails(
            content=content, stage='CURRENT')))
    for attempt in range(30):
        bundle = reader.get_secret_bundle(secret_id, stage='CURRENT').data
        actual = json.loads(base64.b64decode(bundle.secret_bundle_content.content))
        if actual == settings:
            print('CURRENT Vault configuration verified. Restart application to load it.')
            break
        time.sleep(2)
    else:
        raise RuntimeError('Version propagation timed out')
except Exception:
    raise SystemExit('Vault update/verification failed; inspect private configuration and permissions. Raw details suppressed.') from None
PY
```

Alternatively, in OCI Console locate `home-movies-runtime`, create a secret
version with the complete JSON as plaintext secret content, and mark that version
CURRENT. Base64 above is transport encoding, not encryption; OCI Vault encrypts
stored content. Do not base64-encode the JSON yourself when choosing plaintext
content in the console.

## 3. Restart and validate

Vault updates do not hot-reload into running workers. Use
[Bastion access](vm-maintenance.md), then:

```bash
sudo systemctl restart home-movies
sudo systemctl is-active home-movies
```

Check the site's HTTPS health, login, a movie and an incognito share. Application
startup verifies the bucket is private and the B2 key has the expected scope.
A routine GitHub app deployment also restarts the service and loads CURRENT,
but no rebuild is necessary for a configuration-only change.

## Updates and rollback

Always start from the existing **complete** CURRENT JSON, not the illustrative
example. The update replaces the entire object, rather than merging fields.
You can save CURRENT privately using the same explicit destination profile:

```bash
python - <<'PY'
import base64, logging, os
from pathlib import Path
import oci
logging.disable(logging.CRITICAL)
os.umask(0o077)
path = Path('.local/runtime-app.json')
if path.exists():
    raise SystemExit('File exists; preserve or move it before exporting CURRENT.')
try:
    config = oci.config.from_file(profile_name=os.environ['OCI_PROFILE'])
    bundle = oci.secrets.SecretsClient(config).get_secret_bundle(
        os.environ['HM_RUNTIME_SECRET_OCID'], stage='CURRENT').data
    path.write_bytes(base64.b64decode(bundle.secret_bundle_content.content))
    path.chmod(0o600)
    print('CURRENT saved privately; no content printed.')
except Exception:
    raise SystemExit('Export failed; raw details suppressed.') from None
PY
```

Edit this file locally, preserve unchanged fields and publish with step 2.
For a password change, generate a replacement hash without printing it:

```bash
python - <<'PY'
import getpass, json
from pathlib import Path
from werkzeug.security import generate_password_hash
path = Path('.local/runtime-app.json')
settings = json.loads(path.read_text())
settings['PASSWORD_HASH'] = generate_password_hash(getpass.getpass('New site password: '))
path.write_text(json.dumps(settings, indent=2) + '\n')
path.chmod(0o600)
PY
```

For B2 key rotation, create another restricted playback key, update both key fields,
publish, restart and verify playback before revoking the old key. Retain the same
`SECRET_KEY` unless you intentionally want to invalidate signed sessions.
If all existing login/share/QR tokens must be revoked, stop the app and remove the
disposable SQLite files as described in the [operator guide](operators-guide.md);
a password change alone does not accomplish that.

To roll back, select the previous known-good Vault version as CURRENT and restart
the application. A revoked B2 key cannot be restored by selecting an old version;
use a working restricted key instead. Keep private JSON files only as long as
needed, and never delete the production Caddy certificate or token directories
as part of configuration-file cleanup.
