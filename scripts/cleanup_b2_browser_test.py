#!/usr/bin/env python3
"""Remove only the synthetic object versions recorded by browser-test preparation."""
import json
import logging
import sys
from pathlib import Path
from b2_preflight import load_config


def main():
    logging.disable(logging.CRITICAL)
    local = Path(__file__).resolve().parents[1] / '.local'
    state_path = local / 'browser-test-state.json'
    try:
        from b2sdk.v3 import B2Api, InMemoryAccountInfo
        state = json.loads(state_path.read_text())
        entry = state['entry']
        if not entry.startswith('_migration-test/') or not entry.endswith('.hls/output.m3u8'):
            raise ValueError('Invalid fixture scope')
        prefix = entry.rsplit('/', 1)[0] + '/'
        objects = state['objects']
        if not all(obj['name'].startswith(prefix) and obj['id'] for obj in objects):
            raise ValueError('Invalid fixture object list')
        cfg = load_config(local / 'b2-upload-test.json')
        api = B2Api(InMemoryAccountInfo())
        api.authorize_account(cfg['application_key_id'], cfg['application_key'])
        allowed = api.account_info.get_allowed()
        if (allowed['namePrefix'] != '_migration-test/' or len(allowed['buckets'] or []) != 1
                or allowed['buckets'][0]['id'] != cfg['bucket_id']):
            raise ValueError('Uploader scope mismatch')
        remaining = []
        for obj in objects:
            try:
                api.delete_file_version(obj['id'], obj['name'])
            except Exception:
                remaining.append(obj)
        if remaining:
            state['objects'] = remaining
            state_path.write_text(json.dumps(state, indent=2) + '\n')
            print('Synthetic cleanup incomplete; state preserves remaining versions.', file=sys.stderr)
            return 1
        state_path.unlink()
        print('PASS: recorded synthetic browser fixture versions removed. No other objects touched.')
        return 0
    except Exception:
        print('Synthetic cleanup failed; raw account details suppressed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
