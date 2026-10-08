# Checkpoint 8 — private A1 VM and application deployment

Status: application plan and ARM64 build are ready for live GitHub validation.
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

Initial local validation: 118 Python tests passed with 97.54% statement coverage;
four application Terraform mock tests passed. Live plan, image publication, VM
bootstrap, Run Command and maintenance access still require validation.

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
