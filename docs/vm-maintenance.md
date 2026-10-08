# Home Movies VM maintenance through OCI Bastion

Terraform provisions the Bastion in the application compartment and enables its
managed SSH plugin on the Oracle Linux VM. The VM has no public IP. Port 22 is
allowed only from the Bastion's private endpoint. GitHub deployment uses Run
Command independently of these SSH sessions.

Set the protected environment variable `OCI_BASTION_CLIENT_CIDR` to your current
public IPv4 address followed by `/32` before provisioning. If it changes, update
the variable and apply the reviewed Terraform change. Do not open SSH to the
Internet. Sessions last at most one hour.

For occasional maintenance:

1. Sign into the destination OCI tenancy and open the Home Movies Bastion.
2. Create a **Managed SSH** session targeting the Home Movies instance, with
   operating-system user `opc` and a one-hour lifetime.
3. Upload your local **public** SSH key, normally `$HOME/.ssh/id_rsa.pub`.
4. Wait for the session to become active, then use **Copy SSH command**.
5. Replace the command's private-key placeholder with `$HOME/.ssh/id_rsa` and run
   it locally. The private key stays on your computer. The agent supplies session
   access without a permanent operator key in Terraform or VM metadata.
6. Delete the Bastion session when finished, or allow it to expire.

Start with `systemctl status caddy home-movies` and `sudo cloud-init status`.
Use `sudo journalctl -u home-movies` or `sudo journalctl -u caddy` locally when
needed. Host logs can contain operational/private details; do not paste raw logs,
runtime settings, tokens or movie URLs into the public repository or CI artifacts.
Do not edit application settings through SSH: the named OCI Vault secret is the
runtime configuration source. A new deployment/restart reloads the secret.

If the Bastion agent or host is unhealthy, an SSH session may not be available.
OCI Run Command and the instance console are separate troubleshooting options;
their functionality and permissions will be checked during the live checkpoint.

[OCI managed SSH sessions](https://docs.oracle.com/en-us/iaas/Content/Bastion/Tasks/create-session-managed-ssh.htm).
