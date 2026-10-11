"""Mask private configuration before GitHub echoes composite-action inputs."""
import json
import os
import sys

from oci_wif import WifError, mask


def configure(value):
    """Validate the complete private-value list before emitting any GitHub log masks."""
    values = json.loads(value)
    if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
        raise WifError('Configuration masks are missing or malformed.')
    for value in values:
        mask(value)


def main():
    """Register configured log masks and report malformed input without echoing it."""
    try:
        configure(os.environ['OCI_PRIVATE_CONFIG_MASKS'])
        return 0
    except Exception:
        print('Configuration masking failed; raw details suppressed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
