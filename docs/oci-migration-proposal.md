# Accepted OCI and Backblaze architecture

The implementation runs a dedicated private OCI A1 VM with 1 OCPU, 2 GB RAM and
a 50 GB boot volume, host Caddy, an ARM64 Podman/Gunicorn/Flask container, a public
TCP NLB, NAT gateway, OCI Bastion and OCI Vault. Backblaze B2 stores the private
movie library through native APIs. SQLite replaces the disposable Redis token
cache. See [Checkpoint 8](checkpoint-8-application-deployment.md) and
[Checkpoint 9](checkpoint-9-mp4-and-library-transfer.md) for measured validation.

## Shared tenancy budget

The other app uses 2 A1 OCPUs, 12 GB RAM and 100 GB block/boot storage. Home Movies
adds 1 OCPU, 2 GB RAM and 50 GB boot storage: current destination totals are
3 A1 OCPUs, 14 GB RAM and 150 GB block/boot storage. The flexible load balancer
belongs to the other app; Home Movies uses its own NLB. A standard Vault/software
key and small private state bucket avoid storing the media library in OCI.
Temporary E4 migration resources run in the separate source tenancy and are
removed after verification; they do not consume the destination's free allowance.

B2 publishes $6.95/TB/month with the first 10 GB free. The 217,956,271,191-byte
source library therefore has an estimated steady-state storage cost of about
$1.45/month before taxes and extra retained versions. Downloads are free up to
three times average monthly storage; occasional family viewing is expected to
fit, but byte-hour averaging matters in the first billing cycle. Extra download
usage is $0.01/GB. Class A/B/C calls are free for PAYG customers. These are estimates,
not a billing guarantee. [Published B2 pricing, checked October 8, 2026](https://www.backblaze.com/cloud-storage/pricing)

## Networking and certificates

The owner-created application compartment contains a dedicated VCN. Its public
NLB subnet uses an Internet gateway; its private app subnet uses NAT for B2,
GHCR, ACME and package updates. The A1 VM has no public IP. Web and health ingress
comes from the NLB; SSH ingress comes only from the Bastion private endpoint.
Flask is published only on VM loopback port 5000. IMDSv1 is disabled.

The NLB forwards TCP 80/443 without terminating TLS. Caddy serves the configured
public DNS hostname and obtains/renews Let's Encrypt certificates automatically.
Certificates live in `/var/lib/caddy` on the boot volume; no separate block volume
or Kubernetes PV is needed. GoDaddy hosts DNS externally. Public DNS now reaches
the new NLB for the synthetic pilot, and a trusted certificate was verified.
Bastion injects a session public key for occasional maintenance; private operator
keys remain on the laptop. [VM maintenance](vm-maintenance.md)

## Private media delivery

The bucket stays Private. The runtime key is bucket-restricted and contains only
read/list/share capabilities. Before issuing grants the app verifies the private
bucket and its key scope, without relying on cached bucket visibility. It never
issues an empty/bucket-wide download prefix. Requested movies must be present in
the discovered catalog.

For HLS, Flask rewrites every playlist: child playlists point to authenticated
application routes and segments/keys/maps point directly to B2. The grant ends
with the movie directory's trailing slash. External references, traversal and
unsupported dynamic URI features fail closed. Video bytes bypass Flask.

Standalone MP4s use the same native B2 grant machinery with an authenticated
redirect. Their grant prefix is the complete original filename. Fresh native
listings before and after token issuance require that only that file matches;
collisions including non-catalog sidecars reject playback. B2 itself enforces a
prefix, so future uploads must preserve this invariant throughout token lifetime.
The [manual upload runbook](manual-b2-upload.md) checks existing and candidate
names before every upload. No alternate S3/proxy fallback is implemented.

Download tokens are capped at two hours and the remaining parent authorization,
with a latency/skew margin. Authentication is rechecked after remote calls.
Invalid supplied share tokens cannot fall back to logged-in access. Responses
use no-store and no-referrer. Direct bearer URLs remain usable until expiry;
logout or deleting a share does not revoke a token already issued by B2.
[Native B2 grant semantics](https://www.backblaze.com/apidocs/b2-get-download-authorization)

## Authentication and secrets

SQLite stores login, QR and share tokens only. Reads enforce expiry regardless
of cleanup; a periodic cleanup removes expired rows, and a 32 MiB database limit
bounds growth. QR consumption is atomic and single-use. SQLite is disposable:
there is no backup/restore requirement. Losing it signs viewers out and invalidates
stored shares. The source username/password are reused, with a password hash and
a persistent random Flask session secret in the destination runtime configuration.

Real B2/login/session values live in one OCI Vault JSON secret fetched with the
VM's instance principal. Terraform creates only secret metadata plus an empty
JSON placeholder and ignores later content changes. Application secrets are
not in Terraform state, GitHub Actions, images or public logs. Actual identifiers,
DNS/contact values and private media inventories stay outside Git.
[Public repository configuration](public-repository-configuration.md)

## Automation, uploads and acceptance

Terraform and GitHub WIF manage destination infrastructure and software releases.
Home Movies identities/permissions are separate; the identity domain's existing
GitHub issuer trust is shared additively with the other app. All trusted branch
pushes are eligible for future releases. CI tests require no live credentials and
force coverage above 90 percent. Native ARM64 builds publish immutable digests;
Run Command invokes a digest-restricted helper and checks local health.

The one-time media copy uses a temporary isolated source helper and native OCI/B2
rclone backends, with full streamed content verification. Five zero-byte folder
markers are handled separately through the native API. Future uploads remain
manual, preserving every original filename and prefix. No backup program, OKE,
Redis node, certificate PV, advanced monitoring, or renamed/versioned catalog
system is required. The branch is merged only after real-library acceptance.
[Automation and cutover](automation-and-cutover-plan.md)
