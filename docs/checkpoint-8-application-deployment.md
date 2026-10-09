# Checkpoint 8 — private A1 VM and application deployment

Status: infrastructure applied; live B2 integration passed; corrected deployment
workflow is being validated.
All changes remain on the migration branch. Source infrastructure, its secrets,
movie objects, DNS and the default branch are unchanged.

## Application infrastructure

The application module uses the existing private state bucket and software-key
Vault. It creates a dedicated VCN, public NLB subnet, private application subnet,
NAT gateway, Internet gateway, security groups, Bastion and one Oracle Linux 9
A1 instance with 1 OCPU, 2 GB RAM and a 50 GB boot volume. IMDSv1 is disabled.
The VM is named `homemovies-app`; no permanent SSH key or public VM IP is added.
Bastion permits one operator IPv4 /32 and one-hour managed SSH sessions.
Its service endpoint has no attached NSG, so the subnet security list permits
outbound TCP 22 to the private application subnet. It adds no inbound rule;
VM SSH ingress remains restricted to the Bastion endpoint’s /32.

Terraform imports the seeded runtime dynamic group and narrows its membership
to this VM. Its compartment policy grants access to one runtime secret and the
VM's own Run Command executions. Terraform creates the runtime secret with an
empty JSON placeholder; the owner writes real settings directly to OCI Vault.
Terraform ignores content changes, so subsequent applies cannot reset the secret.
No real B2 key, username, password hash or session secret is a Terraform input.

The infrastructure workflow authenticates as `homemovies-infrastructure`, reads
private bootstrap outputs, uses the native OCI backend and prints only aggregate
plan counts. State and output metadata stay in the private bucket. Plans are not
public artifacts. The operation is selected with repository variable
`HOME_MOVIES_APPLICATION_OPERATION=plan` or `apply`; enable the workflow with
`ENABLE_HOME_MOVIES_APPLICATION_INFRA=true`. It accepts repository branch pushes
and manual runs, serializes infrastructure operations, and requires no reviewer
approval. Workflow dispatch becomes available after merge to the default branch;
branch pushes exercise the new workflow before cutover.

## Application release

The release workflow runs native ARM64 tests with a greater-than-90% coverage gate,
then builds and publishes a software-only image to the repository's GHCR package.
The image uses its Git commit as a tag; deployment consumes the immutable SHA-256
digest. No credentials or movie objects are in the build context. The package
must be Public so the VM can pull without another credential. Publishing a new
GHCR package starts Private; its visibility must be changed once before deployment.

`ENABLE_HOME_MOVIES_IMAGE_BUILD=true` enables build/publish. Separately,
`ENABLE_HOME_MOVIES_APP_DEPLOY=true` enables the dependent Run Command deployment
job in `homemovies-production`. Its service identity checks the target instance's
compartment and running state, and submits only the installed digest-restricted
helper. It polls asynchronous execution and treats failure/timeout as deployment
failure. Application health is checked on loopback before success. Registry and
OCI runner credentials are cleaned up after each job.

Caddy and SQLite use boot-volume directories; there are no extra block volumes.
The runtime secret contains the existing source username, a hash of its existing
password, a new persistent random session key and the private B2 playback key.
The source password is read only to create the hash; no plaintext password is
saved. The token database remains disposable and is not backed up.

## Configuration privacy and live validation

Actual DNS/contact email, OCI resource identifiers and operator IP are in ignored
owner-only local files and GitHub environment variables. The mask list is refreshed
before workflow runs so inputs are not exposed in public logs. B2 and login secrets
are written directly to the destination Vault, without passing through GitHub.

Current local validation: 119 Python tests passed with 97.54% statement coverage;
four application Terraform mock tests passed. The [application plan/apply](https://github.com/eshneken/flask-homemovies/actions/runs/37859649556)
passed with 35 creates, one update, one import and no deletions. The VM is RUNNING,
has no public IP and has IMDSv1 disabled. Cloud-init completed with zero errors,
and managed Bastion SSH was validated. A narrow Bastion egress correction was
[applied through GitHub](https://github.com/eshneken/flask-homemovies/actions/runs/37861102045).

The native ARM64 build passed and the GHCR image was verified anonymously pullable.
Run Command deployment completed in OCI with exit code 0, but the GitHub service
identity received 404 responses while reading its execution result. Extending the
polling window did not resolve that denial. The application policy now explicitly
grants the deployment group read access to command executions in this compartment;
it grants no execution-update permission. This correction is being validated.
The job allows a 15-minute polling window and a 20-minute job timeout for normal
agent delivery/reporting. The installed helper bounds each host operation and a
remote command has a ten-minute execution limit.

Existing login credentials were verified over an encrypted Bastion tunnel. Live
synthetic playback passed from the destination VM: nested manifest rewriting,
direct B2 Range downloads, production-origin CORS and guest sharing. Anonymous
B2 access, neighboring movie-prefix access, invalid shares and untrusted Hosts
were rejected. Production intentionally excludes `_migration-test/` objects; the
test temporarily selected that exact synthetic movie through private Vault
configuration. The production configuration was restored afterward. No files or
prefixes were renamed and no real movies have been copied yet.

Runtime credentials were written directly into Vault. A read of private application
Terraform state confirmed the content remained the empty placeholder and did not
contain the B2 key, password hash or session secret.

Public DNS remains pointed at the old application until the later cutover
checkpoint. We can test only public health and unauthenticated routing over HTTP using the
configured Host header. Login credentials and playback tokens must not be sent
over public HTTP; private authenticated tests use an encrypted Bastion tunnel.
We can validate private application health before cutover. Public Let’s Encrypt
issuance with standard Caddy challenges requires DNS to reach the new NLB;
certificate issuance and browser HTTPS checks therefore remain cutover checks.
The final documentation migration, exact-prefix OCI-to-B2 copy and manual upload
runbook are separate checkpoints before merging the branch.

References: [GitHub native ARM64 runners](https://github.blog/changelog/2025-08-07-arm64-hosted-runners-for-public-repositories-are-now-generally-available/),
[GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
[OCI Run Command](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/runningcommands.htm).

## Next checkpoint: library compatibility and transfer

Read-only source inventory found 12,061 objects totaling 217,956,271,191 bytes
(about 218 GB), including seven HLS master playlists and 30 standalone MP4 files.
The current migrated catalog supports HLS; MP4 playback must be implemented and
validated before library migration or cutover. Preserve every filename and prefix.
No source movie objects have been copied or modified. The B2 transfer and manual
upload runbook remain pending, along with the full documentation migration.
