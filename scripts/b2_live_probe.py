#!/usr/bin/env python3
"""Upload disposable synthetic fixtures and verify native B2 download boundaries."""

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

from b2_preflight import UnsafeConfiguration, check_private_bucket, load_config


class ProbeFailure(ValueError):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--playback-config', type=Path, required=True)
    parser.add_argument('--upload-config', type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    uploaded = []
    uploader_bucket = None
    stage = 'configuration'
    success = False
    try:
        from b2sdk.v3 import B2Api, InMemoryAccountInfo
        import requests
        playback_config = load_config(args.playback_config)
        upload_config = load_config(args.upload_config)
        if upload_config['bucket_id'] != playback_config['bucket_id']:
            raise ProbeFailure('Upload and playback buckets must match.')
        if upload_config['application_key_id'] == playback_config['application_key_id']:
            raise ProbeFailure('Uploader must use its own standard application key ID.')
        stage = 'authentication'
        playback = B2Api(InMemoryAccountInfo())
        uploader = B2Api(InMemoryAccountInfo())
        playback.authorize_account(playback_config['application_key_id'], playback_config['application_key'])
        uploader.authorize_account(upload_config['application_key_id'], upload_config['application_key'])
        stage = 'key scope and privacy validation'
        check_private_bucket(playback, playback_config['bucket_id'])
        scope = uploader.account_info.get_allowed()
        buckets = scope.get('buckets')
        if 'listAllBucketNames' in scope.get('capabilities', []):
            raise ProbeFailure('Create a replacement uploader key with Allow List All Bucket Names unchecked.')
        if (not isinstance(buckets, list) or len(buckets) != 1
                or buckets[0].get('id') != upload_config['bucket_id']
                or scope.get('namePrefix') != '_migration-test/'
                or not {'writeFiles', 'deleteFiles'} <= set(scope.get('capabilities', []))
                or set(scope.get('capabilities', [])) & {'writeKeys', 'deleteKeys', 'listAllBucketNames'}):
            raise ProbeFailure('Uploader must be restricted to the test prefix and bucket.')
        uploader_bucket = uploader.get_bucket_by_id(upload_config['bucket_id'])
        bucket = playback.get_bucket_by_id(playback_config['bucket_id'])
        base = '_migration-test/' + uuid.uuid4().hex + '/'
        prefix = base + 'Example Movie.hls/'
        fixture = b'synthetic-data-only-0123456789'
        stage = 'synthetic fixture upload'
        for name, data, mime in (
            (prefix + 'segment é.ts', fixture, 'video/mp2t'),
            (prefix + 'output.m3u8', b'#EXTM3U\n#EXTINF:2,\nsegment%20%C3%A9.ts\n#EXT-X-ENDLIST\n', 'application/vnd.apple.mpegurl'),
            (base + 'Other.hls/segment.ts', fixture, 'video/mp2t'),
            (base + 'Example Movie.hls-extra/segment.ts', fixture, 'video/mp2t'),
        ):
            item = uploader_bucket.upload_bytes(data, name, content_type=mime)
            uploaded.append((item.id_, name))

        def fetch(name, token=None, headers=None):
            url = bucket.get_download_url(name)
            if token is not None:
                url += '?' + urlencode({'Authorization': token})
            return requests.get(url, headers=headers, timeout=(10, 20), allow_redirects=False)

        stage = 'anonymous download rejection'
        if fetch(prefix + 'segment é.ts').status_code not in (401, 403, 404):
            raise ProbeFailure('Anonymous request was not denied.')
        print('PASS: anonymous download denied.')
        stage = 'movie grant and exact filename download'
        token = bucket.get_download_authorization(prefix, 60)
        response = fetch(prefix + 'segment é.ts', token)
        if response.status_code != 200 or response.content != fixture:
            raise ProbeFailure('Authorized download did not match fixture.')
        print('PASS: movie-scoped download preserves spaces and Unicode filenames.')
        stage = 'Range request'
        response = fetch(prefix + 'segment é.ts', token, {'Range': 'bytes=0-3'})
        if response.status_code != 206 or response.content != fixture[:4]:
            raise ProbeFailure('Range request failed.')
        print('PASS: Range request returns exact requested bytes.')
        stage = 'cross-movie and sibling-prefix rejection'
        for name in (base + 'Other.hls/segment.ts', base + 'Example Movie.hls-extra/segment.ts'):
            if fetch(name, token).status_code not in (401, 403, 404):
                raise ProbeFailure('Cross-prefix request was not denied.')
        print('PASS: cross-movie and sibling-prefix downloads denied.')
        stage = 'download token expiry'
        short_token = bucket.get_download_authorization(prefix, 2)
        if fetch(prefix + 'segment é.ts', short_token).status_code != 200:
            raise ProbeFailure('Short token was not initially valid.')
        time.sleep(4)
        if fetch(prefix + 'segment é.ts', short_token).status_code not in (401, 403, 404):
            raise ProbeFailure('Expired token was not denied.')
        print('PASS: B2 rejects expired download token.')
        success = True
    except (UnsafeConfiguration, ProbeFailure) as error:
        print(f'FAIL during {stage}: {error}', file=sys.stderr)
    except Exception:
        print(f'FAIL during {stage}; raw API details suppressed.', file=sys.stderr)
    finally:
        cleanup_ok = True
        for file_id, name in uploaded:
            try:
                # Delete only the exact versions returned by this run's own uploads.
                uploader_bucket.api.delete_file_version(file_id, name)
            except Exception:
                cleanup_ok = False
        if uploaded and cleanup_ok:
            print('PASS: all synthetic versions created by this run removed.')
        elif uploaded:
            print('FAIL: synthetic cleanup incomplete; inspect only _migration-test/.', file=sys.stderr)
            success = False
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
