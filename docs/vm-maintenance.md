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

Get your current public IPv4 address using a trusted IP-check service. Compare it
with the Bastion client CIDR allow list in the OCI console. If it has changed,
set GitHub environment `homemovies-infrastructure` variable
`OCI_BASTION_CLIENT_CIDR` to that IPv4 address followed by `/32`, update the private
configuration masks, and run the infrastructure plan/apply workflow. This updates
the Bastion allow list; do not open the VM's SSH port to the Internet. A VPN or
changed home IP can prevent connection even when a session is active.

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
3. Verify the client allow list contains your current IPv4 `/32`.
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

## 4. Finish and troubleshoot

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
