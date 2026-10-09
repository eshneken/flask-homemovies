# Deployment has moved to GitHub Actions

OCI DevOps build/command specifications and the source Container Instance pipeline
are retired on this migration branch. The implementation uses Terraform with
GitHub workload identity federation and immutable ARM64 releases to an OCI VM.
See [the application README](../README.md), [infrastructure](../infra/README.md)
and [automation/cutover](../docs/automation-and-cutover-plan.md).

The default branch and existing source deployment remain intact until final
migration acceptance. Original OCI DevOps artifacts are available in Git history;
do not use them to deploy this branch.
