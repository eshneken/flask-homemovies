#!/usr/bin/env python3
"""Add only the local browser test CORS rule using the installed native B2 CLI."""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from b2_preflight import load_config


def main():
    logging.disable(logging.CRITICAL)
    root = Path(__file__).resolve().parents[1]
    cache = root / '.local/b2-cors-cli.sqlite'
    try:
        from b2sdk.v3 import B2Api, InMemoryAccountInfo
        playback = load_config(root / '.local/b2-preflight.json')
        config = load_config(root / '.local/b2-upload-test.json')
        if config['bucket_id'] != playback['bucket_id']:
            raise ValueError('Bucket mismatch')
        api = B2Api(InMemoryAccountInfo())
        api.authorize_account(config['application_key_id'], config['application_key'])
        allowed = api.account_info.get_allowed()
        buckets = allowed.get('buckets')
        if (not isinstance(buckets, list) or len(buckets) != 1
                or buckets[0].get('id') != config['bucket_id']
                or not {'writeBuckets', 'readBucketEncryption'} <= set(allowed['capabilities'])):
            raise ValueError('Bucket administration permission unavailable')
        bucket = api.list_buckets(bucket_id=config['bucket_id'], use_cache=False)[0]
        if bucket.type_ != 'allPrivate':
            raise ValueError('Bucket is not private')
        before = bucket.cors_rules
        rule = {'corsRuleName': 'homemovies-local-test',
                'allowedOrigins': ['http://127.0.0.1:5055'],
                'allowedOperations': ['b2_download_file_by_name'],
                'allowedHeaders': ['range'],
                'exposeHeaders': ['content-length', 'content-range', 'accept-ranges'],
                'maxAgeSeconds': 300}
        after = [r for r in before if r['corsRuleName'] != rule['corsRuleName']] + [rule]
        snapshot = root / '.local/b2-cors-before.json'
        if not snapshot.exists():
            snapshot.write_text(json.dumps(before, indent=2) + '\n')
            snapshot.chmod(0o600)
        env = os.environ.copy()
        env.update(B2_ACCOUNT_INFO=str(cache), B2_APPLICATION_KEY_ID=config['application_key_id'],
                   B2_APPLICATION_KEY=config['application_key'])
        completed = subprocess.run(['b2', 'bucket', 'update', bucket.name, 'allPrivate',
                                    '--cors-rules', json.dumps(after)], env=env,
                                   capture_output=True, timeout=60)
        if completed.returncode:
            raise ValueError('CLI request failed')
        fresh = api.list_buckets(bucket_id=config['bucket_id'], use_cache=False)[0]
        if fresh.type_ != 'allPrivate' or fresh.cors_rules != after:
            raise ValueError('Post-update verification failed')
        print('PASS: exact local-origin download CORS rule installed; existing rules preserved and bucket remains private.')
        return 0
    except Exception:
        print('CORS update failed; raw account/CLI details suppressed.', file=sys.stderr)
        return 1
    finally:
        # Remove only this tool's isolated credential cache, never the user's CLI cache.
        for suffix in ('', '-journal', '-wal', '-shm'):
            cache.with_name(cache.name + suffix).unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(main())
