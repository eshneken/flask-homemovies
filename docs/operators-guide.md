# Home Movies operator guide

Use [Bastion access](vm-maintenance.md) for a temporary `opc` SSH session to the
private VM. These commands run **on the VM** unless marked as laptop commands.
Infrastructure and image releases use GitHub Actions; SSH is for diagnostics and
occasional maintenance. Private configuration belongs in OCI Vault and GitHub
environment variables, not this repository.

## Check service and boot health

```bash
sudo systemctl is-enabled caddy home-movies
sudo systemctl is-active caddy home-movies
sudo systemctl status caddy home-movies --no-pager
sudo cloud-init status --long
sudo systemctl --failed
sudo podman ps --filter name=home-movies
sudo journalctl -b -u caddy -u home-movies --since '15 minutes ago'
```

Both services should be `enabled` and `active`. Cloud-init should have completed
initial host setup. Set `APP_HOSTNAME` to the configured public hostname, then
check loopback routing and the NLB health endpoint:

```bash
APP_HOSTNAME='movies.example.com'
curl --fail --silent --show-error -H "Host: $APP_HOSTNAME" http://127.0.0.1:5000/health
curl --fail --silent --show-error http://127.0.0.1:8080/health
```

From your laptop, check `https://$APP_HOSTNAME/health`, sign in, play and seek a
movie, and open a Share Video link in a private browser window. `/health` checks
that Flask responds; it does not verify every B2 object or simulate playback.

## Logs: what exists and where to look

Caddy and Gunicorn write service output to the systemd journal. Podman's configured
log driver is `journald`; use journalctl rather than looking for Docker JSON logs.
Caddy HTTP access logging and Gunicorn request access logging are not enabled.
This avoids recording authenticated query strings as routine request logs.
Startup/error logs can still contain private operational information. Inspect
locally; never publish raw logs, B2 URLs, share links or secret JSON.

```bash
sudo journalctl -u home-movies --since '1 hour ago' --no-pager
sudo journalctl -u caddy --since '1 hour ago' --no-pager
sudo journalctl -u home-movies -u caddy -f
sudo journalctl -b -1 -u home-movies -u caddy --no-pager
sudo journalctl --disk-usage
```

`-f` follows new output; Ctrl-C stops following. `-b -1` selects the previous boot
when retained. Host provisioning logs are `/var/log/cloud-init.log` and
`/var/log/cloud-init-output.log`. OS/package logs also live under `/var/log` and
normally use the host's logrotate rules. Agent diagnostics are under
`/var/log/oracle-cloud-agent` when present; inspect them if Bastion or Run Command
is unavailable. Treat cloud-init and agent logs as private too.

## Disk paths and safe cleanup

| Host path | Purpose | Maintenance |
| --- | --- | --- |
| `/var/log/journal` | Persistent systemd service and OS journal | Use journalctl vacuum commands below. |
| `/run/log/journal` | Early boot/runtime journal | Managed by journald; do not manually remove active files. |
| `/var/log` | Cloud-init, agent, OS and package logs | Check sizes and logrotate policy before removing old archives. |
| `/var/lib/containers/storage` | Root Podman cached images and containers | Remove unused images only after choosing which rollback images to retain. |
| `/var/lib/caddy/.local/share/caddy` | ACME account, certificates and keys | Preserve; removing it forces certificate reissuance and may hit ACME limits. |
| `/var/lib/caddy/.config/caddy` | Caddy saved configuration | Preserve; the managed Caddyfile remains the configuration source. |
| `/var/lib/home-movies/tokens` | Disposable SQLite database and transient rollback journal | Automatic expiry cleanup; no routine manual purge or backup. |
| `/etc/home-movies` | Digest, deployment configuration and Vault secret reference | Preserve; restrict access to private configuration. |
| `/etc/caddy/Caddyfile` | HTTPS/reverse proxy configuration | Validate before reloading. |

```bash
df -h /
sudo du -sh /var/log /var/lib/containers/storage /var/lib/caddy /var/lib/home-movies/tokens
sudo podman system df
sudo journalctl --disk-usage
```

Journald retention is configured in
`/etc/systemd/journald.conf.d/home-movies.conf`: persistent journals target 100 MiB,
retain at most 14 days, and leave 1 GiB free; runtime journals target 32 MiB.
Active files and rotation granularity can make total usage exceed the target
slightly. This policy applies to the **entire VM journal**, not just this app.
It does not govern ordinary files in `/var/log`. To remove older journal records
immediately, after inspecting anything needed for troubleshooting:

```bash
sudo journalctl --rotate
sudo journalctl --vacuum-time=14d --vacuum-size=100M
sudo journalctl --disk-usage
```

These commands remove archived logs across all journal units; retained diagnostic
history is lost. Never `rm` an active journal. Review `/etc/logrotate.conf` and
`/etc/logrotate.d/` for regular log files; avoid blanket deletion of `/var/log`.
If image storage grows after releases, inspect unused images:

```bash
sudo podman images --digests
sudo podman image prune
```

The default prune removes dangling images and asks for confirmation. Previous
digest-only releases can be dangling too: tag any rollback image you want to
retain before using prune, for example `sudo podman tag '<desired digest>'
localhost/home-movies:rollback`. Keep the application running during image cleanup
so its current image remains in use. Do not prune while the service is stopped.
Do not use `podman system prune --all` as routine maintenance: it removes unused
tagged rollback images as well. The running digest remains in
`/etc/home-movies/image.env`; a cached image is required for boot because the
service uses `--pull=never`. Never delete `/var/lib/containers/storage` manually.

## Restart and recovery

Caddy is a host RPM service. Gunicorn runs in Podman under `home-movies.service`.
SQLite is a Python library inside that same process. No database service needs
starting. Both systemd services retry every five seconds after failures with no
startup-rate cutoff. Podman uses `--replace` to recover from a stale named
container. Boot waits for networking but Vault or B2 might still be unavailable;
retries continue while the services report failure. Caddy may return 502 until the
app has loaded its runtime settings successfully.

Follow [runtime configuration](runtime-configuration.md) to populate or update
Vault, rotate keys or select a previous version. For an application restart after
changing the Vault JSON:

```bash
sudo systemctl restart home-movies
sudo systemctl status home-movies --no-pager
```

For Caddy configuration maintenance:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

If startup fails, check network/NAT connectivity, the Vault secret reference and
instance-principal permissions, B2 key permissions and private bucket status,
SQLite directory ownership, and whether the configured image is cached. Keep raw
settings and errors private. An empty `image.env` is not repaired by reboot;
complete an image deployment through GitHub instead. Do not rerun cloud-init to
repair a deployed VM: it is an initial-provisioning tool, not a host reconciler.
Template changes apply to newly provisioned hosts; Terraform ignores subsequent
`user_data` changes because this provider would otherwise replace the VM. Existing
hosts need a reviewed maintenance change as well. The VM is also protected by
`prevent_destroy`.

A controlled reboot briefly interrupts the site. Before testing, confirm both
services are enabled, there is a deployed image, no deployment is running and the
boot volume is healthy. Record `cat /proc/sys/kernel/random/boot_id`. Keep an
existing login and share link to test persistence, then run:

```bash
sudo systemctl reboot
```

Reconnect through Bastion after the VM returns (create another session if needed),
check that the boot ID changed, and repeat the boot/health checks. Confirm trusted
HTTPS, playback and seeking for HLS and MP4, plus a pre-reboot share link. The
certificate, digest and SQLite token state should survive; expired tokens should
still be denied. SQLite rollback journaling recovers unfinished transactions on
open. Do not delete a `tokens.sqlite-journal` file while the app is running.

If the database ever needs resetting, stop `home-movies` first and remove only
its disposable token database/state; all users must sign in again and existing
shares/QR tokens become invalid. This is recovery, not routine log cleanup.

See [Caddy service/storage documentation](https://caddyserver.com/docs/running),
[journald retention](https://www.freedesktop.org/software/systemd/man/252/journald.conf.html)
and [journalctl](https://www.freedesktop.org/software/systemd/man/255/journalctl.html).
