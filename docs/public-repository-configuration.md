# Public repository configuration

Supply tenancy identifiers, compartment names, hostname/contact settings and
operator IP addresses through the GitHub environments described in
[GitHub Actions setup](github-actions.md). The owner creates the application
compartment; Terraform consumes its supplied OCID and does not own or delete it.

WIF client credentials belong in GitHub environment secrets. Runtime B2 and login
credentials belong in [OCI Vault](runtime-configuration.md), rather than GitHub or
Terraform. Keep local credentials, bucket inventories, movie names, generated
URLs, certificates, state and plans outside Git and public Actions artifacts.
Update `OCI_PRIVATE_CONFIG_MASKS` when private configuration changes. It is a JSON
array of nonempty strings used to mask public workflow output.

Before publishing:

```bash
python scripts/check_public_files.py
```

This check also runs on every push and pull request. It reports file/line/category
without printing matched values. It detects obvious credentials, literal OCI IDs,
personal paths/emails and private artifact filenames; it is not an exhaustive
secret scanner. Helpers suppress raw cloud errors and do not dump secret bundles,
movie inventories or authorized media URLs into public logs.

Keep credentials and runtime configuration out of the software-only container
image. The public GHCR image contains code and dependencies; it loads private
settings only at runtime. Use a GitHub noreply author address for commits if you
want to avoid publishing a personal email. The file check does not inspect Git
commit metadata or historical copies.
