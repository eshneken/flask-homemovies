# Checkpoint 1: private Backblaze setup

This checkpoint records the state at that stage. For current architecture and
remaining work, see [the accepted architecture](oci-migration-proposal.md) and
[Checkpoint 9](checkpoint-9-mp4-and-library-transfer.md).

Work stays on `codex/oci-a1-b2-migration`. The existing application is unchanged.
This checkpoint checks account access and privacy; it does not transfer movies,
issue download grants, deploy infrastructure, or enable B2 playback.

## Create the bucket

1. Sign in to Backblaze. Under **B2 Cloud Storage**, select **Buckets**, then
   **Create a Bucket**.
2. Choose a globally unique neutral name without family names or other personal
   information. Select **Private**. Leave Object Lock disabled for this setup.
3. Create the bucket and confirm that its access setting says **Private**.
   Record its **Bucket ID** privately.

The bucket is the top-level container; no separate “root” folder is necessary.
Existing movie filenames and prefixes will be copied into it unchanged later.
Do not upload home movies yet. CORS and playback testing come in the next checkpoint.

See [Backblaze bucket instructions](https://www.backblaze.com/docs/cloud-storage-create-and-manage-buckets).

## Create the playback application key

1. Open **Application Keys**, then **Add a New Application Key**. If account setup
   requires generating a master key first, keep it in your password manager.
   Do not use the master key for this application or give it to the migration tools.
2. Name the standard key `homemovies-playback`.
3. Under **Allow Access to Bucket(s)** choose only the new movie bucket.
4. Select **Read Only**. Leave **Allow List All Bucket Names** unchecked.
5. Leave the filename prefix empty: the server must discover all movies within
   this one bucket. Individual browser download grants will later be restricted
   to the selected movie prefix, with a trailing slash.
6. Leave the duration empty for the initial setup, then create the key.
7. Save the displayed **keyID** and **applicationKey** immediately; the secret
   is displayed only once. Do not paste either into chat or a GitHub issue.

The preflight checks the actual returned capabilities rather than trusting the
UI label. It requires `listBuckets`, `listFiles`, `readFiles`, and `shareFiles`,
and rejects write/admin permissions or access to other buckets. If the UI preset
lacks a required capability, stop here; we will create a narrower native API key
at the next checkpoint instead of granting write access.

See [Backblaze key instructions](https://www.backblaze.com/docs/cloud-storage-create-and-manage-app-keys)
and [application key scopes](https://www.backblaze.com/docs/cloud-storage-application-keys).

## Store the local credentials and validate

From the repository directory:

```sh
mkdir -p .local
chmod 700 .local
cp scripts/b2-preflight.example.json .local/b2-preflight.json
chmod 600 .local/b2-preflight.json
```

Edit `.local/b2-preflight.json` locally and replace the three placeholders.
This directory is ignored by Git. Keep this file out of CI artifacts and backups
shared with others. The deployed application's key will later go into OCI Vault.

Use Python 3.10 or newer in a virtual environment:

```sh
python3 -m venv .venv-b2
.venv-b2/bin/python -m pip install -r scripts/requirements-b2-preflight.txt
.venv-b2/bin/python scripts/b2_preflight.py --config .local/b2-preflight.json
```

Expected output: `PASS: private bucket and single-bucket playback key verified. No files changed.`
The tool uses the native B2 SDK, in-memory authorization storage, and a fresh
bucket metadata read. It suppresses raw API errors and prints no bucket names,
IDs, secrets, object paths, or bearer URLs. A failure does not modify the account.
This check does not yet prove that HLS grants, expiry, CORS or manifest rewriting work.

## Stop and review

Confirm the bucket is private and the preflight passes. Then we will test
synthetic HLS files and prove that anonymous downloads and cross-movie access
fail before transferring any home movies.

Source-tenancy migration helpers are authorized separately from the running
application. A later checkpoint will review a dedicated transfer VM and its
isolated resources; IMDSv1 must be disabled. Existing source app resources and
movie objects must not be modified. No helper VM is created by this checkpoint.
