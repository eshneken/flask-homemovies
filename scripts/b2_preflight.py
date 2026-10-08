#!/usr/bin/env python3
"""Read-only native B2 check. Never print account metadata or credentials."""

import argparse
import json
import logging
import stat
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python_app'))
from b2_policy import REQUIRED, READ_CAPABILITIES, UnsafeConfiguration, validate_scope


def check_private_bucket(api, bucket_id):
    validate_scope(api.account_info.get_allowed(), bucket_id)
    # Explicit filter works with a bucket-restricted key. Bypass cached bucket state.
    buckets = api.list_buckets(bucket_id=bucket_id, use_cache=False)
    if len(buckets) != 1 or buckets[0].id_ != bucket_id:
        raise UnsafeConfiguration("Configured bucket could not be verified.")
    if buckets[0].type_ != "allPrivate":
        raise UnsafeConfiguration("Bucket must be private before any media is transferred.")


def load_config(path):
    root = Path(__file__).resolve().parents[1]
    if path.is_symlink() or path.resolve().parent != (root / ".local").resolve():
        raise UnsafeConfiguration("Keep configuration directly in the ignored .local directory.")
    if not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise UnsafeConfiguration("Configuration must be a regular file with permissions 600.")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise UnsafeConfiguration(
            f"Invalid JSON at line {error.lineno}, column {error.colno}. "
            "Check commas and double quotes; credential values are suppressed."
        ) from None
    if not isinstance(data, dict):
        raise UnsafeConfiguration("Configuration must be a JSON object with three fields.")
    for field in ("bucket_id", "application_key_id", "application_key"):
        value = data.get(field)
        if not isinstance(value, str) or not value or value.startswith("<"):
            raise UnsafeConfiguration("Complete all three private configuration fields.")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    # SDK errors and debug logs can contain URLs, account information, or tokens.
    logging.disable(logging.CRITICAL)
    stage = "configuration read"
    try:
        config = load_config(args.config)
        stage = "SDK import; install scripts/requirements-b2-preflight.txt in this Python environment"
        from b2sdk.v3 import B2Api, InMemoryAccountInfo
        api = B2Api(InMemoryAccountInfo())
        stage = "authentication"
        api.authorize_account(config["application_key_id"], config["application_key"])
        stage = "key scope and bucket metadata check"
        check_private_bucket(api, config["bucket_id"])
    except UnsafeConfiguration as error:
        print(f"B2 preflight failed: {error}", file=sys.stderr)
        return 1
    except Exception:
        print(f"B2 preflight failed during {stage}. "
              "Raw error details are intentionally suppressed.", file=sys.stderr)
        return 1
    print("PASS: private bucket and single-bucket playback key verified. No files changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
