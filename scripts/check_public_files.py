#!/usr/bin/env python3
"""Check publishable files for obvious private configuration; never print values."""

import re
import subprocess
import sys
from pathlib import Path


RULES = {
    "literal OCI identifier": re.compile(
        r"\bocid1\.[a-z0-9_]+\.[a-z0-9_]*\.[a-z0-9._-]{16,}", re.I
    ),
    "private key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
    ),
    "GitHub access token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"
    ),
    "cloud access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "personal local path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
}
EMAIL = re.compile(r"(?<![\w.-])[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
EXAMPLE_DOMAINS = {"example.com", "example.net", "example.org", "example.invalid"}
CREDENTIAL = re.compile(
    r"(?i)(?:password|auth_token|client_secret|application_key|secret_key)"
    r"[\w-]*[\s\"']*[:=]\s*([\"'])([^\"'\n]+)\1"
)


def check_file(path):
    """Return findings as (line, category), without returning matched values."""
    findings = []
    sensitive_name = (
        path.name == ".env"
        or (path.name.startswith(".env.") and path.suffix not in {".example", ".sample"})
        or path.name.endswith(
            (".tfstate", ".tfstate.backup", ".tfplan", ".key", ".pem", ".p12", ".pfx", ".sqlite", ".sqlite3")
        )
        or (path.name.endswith((".tfvars", ".tfvars.json")))
    )
    if sensitive_name:
        findings.append((0, "private configuration/artifact filename"))
    data = path.read_bytes()
    if b"\0" in data:
        return findings
    for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        for category, pattern in RULES.items():
            if pattern.search(line):
                findings.append((number, category))
        for match in EMAIL.finditer(line):
            if match.group(1).lower() not in EXAMPLE_DOMAINS:
                findings.append((number, "non-example email address"))
        for match in CREDENTIAL.finditer(line):
            value = match.group(2)
            # Placeholder/context references are intentional public examples.
            if (
                value.startswith(("$", "<", "your-", "YOUR_", "example-"))
                or value in {"None", "null"}
            ):
                continue
            findings.append((number, "possible literal credential"))
    return findings


def main():
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
    ).decode().split("\0")
    failures = 0
    scanned = 0
    for name in sorted(set(filter(None, tracked))):
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        scanned += 1
        for number, category in check_file(path):
            # Locations and categories only; do not leak a rejected value to CI.
            print(f"{name}:{number}: {category}", file=sys.stderr)
            failures += 1
    if failures:
        print(f"Public-file check failed: {failures} finding(s).", file=sys.stderr)
        return 1
    print(f"Public-file check passed: {scanned} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
