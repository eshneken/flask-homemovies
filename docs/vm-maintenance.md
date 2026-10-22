# Private VM access through OCI Bastion

Terraform creates the Bastion service in the application compartment; you create
an expiring **session** when you need access. There is no extra bastion VM.
The app VM has no public IP and permits SSH only from the Bastion private endpoint.
GitHub deploys through OCI Run Command independently of SSH.

## 1. Check prerequisites on your laptop

Use an OCI CLI profile for the **application tenancy**, not another tenancy.
Your operator identity needs permission to read the Bastion/target instance and
create, read and delete Bastion sessions. The VM must be running with OpenSSH,
Oracle Cloud Agent and its Bastion plugin enabled; Terraform enables the plugin.

Bastion accepts SSH clients only from the configured operator/VPN CIDRs. The VM
has no public IP; its port 22 accepts only the Bastion's private endpoint, rather
than allowing direct SSH from the Internet. Public ports 80/443 serve HTTPS
redirects, certificate issuance and the app; port 8080 is private to the NLB.

Configure GitHub environment `homemovies-infrastructure` variable
`OCI_BASTION_CLIENT_CIDRS` as a JSON array, for example
`["192.0.2.1/32", "198.51.100.0/23", "203.0.112.0/20"]`. Use your actual home IP
as a `/32` and canonical network addresses for VPN ranges. Empty lists, invalid
CIDRs, IPv6 and world-open `/0` ranges fail validation. Real addresses belong in
GitHub settings, not source code.

When your IP changes:

1. Edit `OCI_BASTION_CLIENT_CIDRS` in that GitHub environment and refresh
   `OCI_PRIVATE_CONFIG_MASKS` for changed private configuration values.
2. In Actions, run **Home Movies application infrastructure** on `main`, choosing
   operation **plan**, and review the proposed Bastion allow-list update.
3. Run the same workflow with operation **apply**. The allow list updates in place;
   this does not replace the VM, rebuild the image or rerun cloud-init.
4. Create a new Bastion SSH session from an allowed address. OCI applies allow-list
   changes to new sessions; when removing access, delete existing sessions to
   revoke them immediately rather than waiting for the one-hour expiry.

A VPN or changed home IP can prevent connection if its public egress address is
outside this list. See [Oracle's Bastion update behavior](https://docs.oracle.com/en-us/iaas/Content/Bastion/Tasks/update-bastion.htm).

Use a local SSH key. If the public key file is absent, derive it without exposing
the private key:

```bash
umask 077
ssh-keygen -y -f "$HOME/.ssh/id_rsa" > "$HOME/.ssh/id_rsa.pub"
```

Only the `.pub` file goes to OCI. The private key stays on your laptop. Managed
sessions temporarily install your public key; no permanent operator key is stored
in Terraform or VM launch metadata.

## 2. Create a session in the console

1. Select the application tenancy and region in OCI.
2. Open **Identity & Security → Bastion**, select the application compartment and
   open `home-movies-maintenance`.
3. Verify the client allow list contains your current public IP or VPN egress range.
4. Select **Create session** and choose **Managed SSH session**.
5. Select the Home Movies Compute instance in the application compartment. Use
   OS username `opc`, port `22` and its private IP.
6. Upload `$HOME/.ssh/id_rsa.pub` and choose a lifetime of 3,600 seconds (one hour).
7. Create the session and wait until its state is **Active**. If creation fails,
   check the VM's Bastion plugin and Oracle Cloud Agent rather than adding a public
   IP or broad SSH rule.
8. Open the session's action menu and choose **Copy SSH command**. Replace **both**
   private-key placeholders (outer SSH and ProxyCommand SSH) with the full local
   path to your private key. Execute the command on your laptop.
9. On first connection, verify the host fingerprint using an independent trusted
   source before accepting it. Do not disable host-key checking.

The command connects to the Bastion using the session ID, then forwards SSH to
`opc` on the private VM. If your key is passphrase-protected, load it into your
local SSH agent when needed; do not enable agent forwarding to the VM.

## 3. CLI alternative

Install the OCI CLI and configure your application-tenancy profile first. The
following commands run on the laptop. Obtain the Bastion OCID, instance OCID and
private IP from the console or private Terraform outputs; keep these values out
of Git. Replace the example placeholders:

```bash
OCI_PROFILE='TARGET'
OCI_REGION='us-ashburn-1'
BASTION_ID='paste-bastion-id-from-private-output'
INSTANCE_ID='paste-instance-id-from-private-output'
VM_IP='paste-private-ip-from-private-output'
SSH_KEY="$HOME/.ssh/id_rsa"
umask 077
mkdir -p .local
ssh-keygen -y -f "$SSH_KEY" > .local/bastion-operator.pub

SESSION_ID=$(oci --profile "$OCI_PROFILE" --region "$OCI_REGION" \
  bastion session create-managed-ssh \
  --bastion-id "$BASTION_ID" \
  --target-resource-id "$INSTANCE_ID" \
  --target-os-username opc --target-port 22 --target-private-ip "$VM_IP" \
  --ssh-public-key-file .local/bastion-operator.pub \
  --session-ttl 3600 --display-name home-movies-maintenance \
  --wait-for-state ACTIVE --max-wait-seconds 300 \
  --query 'data.id' --raw-output)
```

Stop if session creation fails or `SESSION_ID` is empty. Fetch the service's SSH
command (save locally if needed, never as a public CI artifact):

```bash
oci --profile "$OCI_PROFILE" --region "$OCI_REGION" \
  bastion session get --session-id "$SESSION_ID" \
  --query 'data."ssh-metadata"' --output json
```

Use the returned command and replace both key placeholders as above. For a simple
private-key path without spaces, the equivalent command is:

```bash
BASTION_HOST="host.bastion.$OCI_REGION.oci.oraclecloud.com"
ssh -i "$SSH_KEY" \
  -o "ProxyCommand=ssh -i $SSH_KEY -W %h:%p -p 22 $SESSION_ID@$BASTION_HOST" \
  -p 22 "opc@$VM_IP"
```

If your private-key path contains spaces, use the console/service-generated
command and quote the path inside the ProxyCommand as well. Session creation does
not renew an existing session automatically. If it expires during maintenance,
create a new one; changing the lifetime variable does not extend the old session.

## 4. Patch the host and application trust stores

Run host maintenance through the managed SSH session as `opc`:

```bash
sudo dnf update -y
sudo update-ca-trust extract
rpm -q ca-certificates
sudo dnf needs-restarting -r
```

If a reboot is required, reboot during maintenance, reconnect and confirm
`home-movies` and `caddy` are active and the public HTTPS health check succeeds.
Host updates do not update the Python application container. Rebuild and deploy
the application separately; the build refreshes its Debian certificates and
bootstraps pip from a SHA256-pinned wheel before installing dependencies.

For the October 2026 emSign incident, every application, test and operator venv
needs pip >= 26.2.2 and certifi >= 2026.10.19. From the repository root, activate
the environment, then run:

```bash
python -m pip --disable-pip-version-check install --no-deps -r python_app/requirements-bootstrap.txt
python -m pip install --upgrade 'certifi>=2026.10.19'
python -m pip --version
python -c 'import certifi; print(certifi.__version__)'
```

Updating certifi does not replace pip's independent bundled certificates.
The [Python security advisory](https://discuss.python.org/t/109576) describes
the incident and secure bootstrap. GitHub jobs refresh runner certificates and
bootstrap pip in every newly created environment. Image builds use `--pull
--no-cache` so rebuilding does not reuse an old base or certificate-install layer.

## 5. Finish and troubleshoot

Exit SSH, then delete the session in the console or on the laptop:

```bash
oci --profile "$OCI_PROFILE" --region "$OCI_REGION" \
  bastion session delete --session-id "$SESSION_ID" --force
```

Deletion terminates session access; otherwise the session expires after one hour.
For host health, log locations, retention and restart checks, use the
[operator guide](operators-guide.md).

A connection timeout usually means the client allow list, VPN/public IP, session
state or SSH/plugin health needs checking. Permission denied can indicate the
wrong OS username, wrong key or expired session. If the host or agent is unhealthy,
OCI Compute Run Command and instance console connections are separate recovery
options; Bastion cannot connect to a stopped VM.

[OCI Managed SSH sessions](https://docs.oracle.com/en-us/iaas/Content/Bastion/Tasks/create-session-managed-ssh.htm)
and [CLI command reference](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/bastion/session/create-managed-ssh.html).
