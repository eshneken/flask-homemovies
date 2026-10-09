# Home Movies

Private family movie playback using Flask, native Backblaze B2 storage and one
OCI A1 VM. HLS playlists pass through authenticated Flask routes; media bytes
stream directly from the private B2 bucket. Standalone MP4 playback uses an
authenticated redirect to a short-lived native B2 download URL.

## Deployment architecture

- Private Oracle Linux 9 A1 VM: 1 OCPU, 2 GB RAM and a 50 GB boot volume;
  IMDSv1 disabled and no public VM address.
- Dedicated VCN with a private app subnet, public NLB subnet and NAT gateway.
  The TCP NLB forwards ports 80/443 to Caddy; its health check uses port 8080.
- Host Caddy manages Let's Encrypt HTTPS and stores certificates on the boot
  volume. Podman runs the ARM64 Gunicorn/Flask image on loopback port 5000.
- OCI Vault stores the named runtime JSON secret. SQLite contains disposable
  login, QR and sharing tokens with expiry checks and cleanup; no backup is needed.
- OCI Bastion supplies temporary SSH access. GitHub deploys immutable GHCR
  image digests through OCI Run Command, without SSH credentials.

Infrastructure and deployment use GitHub workload identity federation. Home Movies
has separate infrastructure/deployment identities and compartment-scoped IAM;
the existing identity domain's GitHub issuer trust is shared additively. Application
networking and resources remain separate from other projects. The owner-created
compartment name/OCID, DNS/contact values and resource identifiers are environment
variables, outside Git. Runtime B2/login secrets never pass through GitHub or
Terraform. See [infrastructure](infra/README.md), [configuration](docs/public-repository-configuration.md)
and [architecture](docs/oci-migration-proposal.md).

The migration remains on `codex/oci-a1-b2-migration`; the existing source app and
default branch remain intact until final acceptance. Public DNS now reaches the
new VM for the synthetic pilot. Real-library copy/verification is in progress;
see [Checkpoint 9](docs/checkpoint-9-mp4-and-library-transfer.md).

## Movie layout and uploads

Preserve every filename and prefix, including capitalization, spaces and Unicode.
HLS collections end in `.hls/` and use `output.m3u8` as their entrypoint. Relative
child playlists and segments stay under that movie's prefix. Standalone `.mp4`
files are discovered separately; MP4 fragments inside HLS folders are excluded.
The library refreshes its B2 listing on requests after at most five minutes.

```text
2022/
  Christmas.hls/
    output.m3u8
    output000.ts
    output001.ts
  Birthday.mp4
```

Uploads run manually from the operator's computer, once or twice a year, using a
separate bucket-restricted key. Follow the [native B2 upload runbook](docs/manual-b2-upload.md).
Upload dependencies before the main playlist. Check the entire destination plus
candidate inventory for MP4 filename-prefix collisions before every upload.
B2's native grants match prefixes, so sidecars such as `Birthday.mp4.notes` must
not be added. No CI upload workflow or catalog publishing step is required.

To encode a new HLS movie locally, keep the existing output layout:

```bash
mkdir -p Christmas.hls
ffmpeg -i input.mp4 \
  -vf 'scale=-2:2160' -c:v libx264 \
  -x264opts 'keyint=24:min-keyint=24:no-scenecut' \
  -b:v 8000k -maxrate 10000k -bufsize 20000k \
  -c:a aac -ac 2 -b:a 128k \
  -hls_time 4 -hls_playlist_type vod \
  Christmas.hls/output.m3u8
```

Encoding is separate from migration: do not transcode or rename source files as
part of the OCI-to-B2 copy. Browser compatibility depends on the media codecs;
test real movies on the family devices before final acceptance.

## Local development and tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements-test.txt
python -m coverage run -m unittest discover -s scripts -p 'test_*.py'
python -m coverage report
python scripts/check_public_files.py
```

Tests live in `scripts/test_*.py`. GitHub runs them on every push and PR without
cloud credentials; mocked B2/OCI clients cover authorization, expiry, repository
behavior and infrastructure. Coverage must exceed 90 percent. ARM64 release jobs
also test before publishing. Live service tests are separate and use private
ignored configuration; do not add real credentials to CI tests.

For a local real-B2 synthetic demo, prepare `.local/b2-preflight.json` and the
restricted `.local/b2-upload-test.json` as described in [B2 setup](docs/checkpoint-1-b2-setup.md).
Then follow [the browser checkpoint](docs/checkpoint-3-flask-playback.md).
`HM_CONFIG_FILE` selects an ignored owner-only local JSON configuration. Production
uses `HM_CONFIG_SECRET_OCID` and the VM's instance principal to fetch its Vault
secret. The application factory is `app:create_runtime_app()`; the old OCI bucket,
Redis and command-line username/password flags are retired.

## Provisioning and releases

[Automation and cutover](docs/automation-and-cutover-plan.md) lists the implemented
workflows, environment configuration and remaining acceptance steps. Ordinary
infrastructure/release jobs use `homemovies-infrastructure` and
`homemovies-production`; reviewer approval gates are disabled by owner preference.
Temporary administrator bootstrap workflows remain disabled after setup.

Builds publish software-only ARM64 images to the public GHCR package. An immutable
digest from this project's repository is the only deployment input. Credentials,
private configuration and movies are excluded from the image. The public image
contains no private library. The source Container Instance/OCIR workflow is removed
on this branch so merging cannot trigger an old-source deployment.

For occasional host access and logs, follow [VM maintenance](docs/vm-maintenance.md).
Application settings come from Vault; restart/deploy reloads the secret. SQLite
loss requires viewers to sign in again and invalidates its stored shares/QR tokens.
