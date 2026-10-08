#!/usr/bin/env python3
"""Prepare a playable synthetic HLS movie and ignored local application settings."""
import json
import logging
import secrets
import subprocess
import sys
import uuid
from pathlib import Path
from b2_preflight import check_private_bucket, load_config


def main():
    logging.disable(logging.CRITICAL)
    root = Path(__file__).resolve().parents[1]
    local = root / '.local'
    state_path = local / 'browser-test-state.json'
    created = []
    uploader = None
    success = False
    stage = 'configuration'
    try:
        if state_path.exists():
            print('Browser fixture state already exists; preserve it for validation or clean it first.')
            return 1
        from b2sdk.v3 import B2Api, InMemoryAccountInfo
        from werkzeug.security import generate_password_hash
        cfg = load_config(local / 'b2-preflight.json')
        upload = load_config(local / 'b2-upload-test.json')
        playback = B2Api(InMemoryAccountInfo())
        uploader = B2Api(InMemoryAccountInfo())
        playback.authorize_account(cfg['application_key_id'], cfg['application_key'])
        uploader.authorize_account(upload['application_key_id'], upload['application_key'])
        check_private_bucket(playback, cfg['bucket_id'])
        allowed = uploader.account_info.get_allowed()
        if (upload['bucket_id'] != cfg['bucket_id'] or allowed['namePrefix'] != '_migration-test/'
                or len(allowed['buckets'] or []) != 1
                or allowed['buckets'][0]['id'] != cfg['bucket_id']):
            raise ValueError('Fixture upload scope mismatch')
        bucket = uploader.get_bucket_by_id(cfg['bucket_id'])
        prefix = '_migration-test/' + uuid.uuid4().hex + '/'
        movie = prefix + 'Synthetic Sample.hls/'
        directory = local / 'browser-fixture'
        (directory / 'variant').mkdir(parents=True, exist_ok=True)
        stage = 'local synthetic encoding'
        result = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100',
            '-t', '6', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '48', '-sc_threshold', '0',
            '-c:a', 'aac', '-b:a', '64k', '-f', 'hls', '-hls_time', '2', '-hls_list_size', '0',
            '-hls_segment_filename', str(directory / 'variant/segment%03d.ts'),
            str(directory / 'variant/main.m3u8')], capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError('Synthetic encoding failed')
        (directory / 'output.m3u8').write_text('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=600000,RESOLUTION=320x180\nvariant/main.m3u8\n')
        stage = 'synthetic upload'
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                name = movie + path.relative_to(directory).as_posix()
                mime = 'application/vnd.apple.mpegurl' if path.suffix == '.m3u8' else 'video/mp2t'
                uploaded = bucket.upload_bytes(path.read_bytes(), name, content_type=mime)
                created.append({'id': uploaded.id_, 'name': name})
        password = secrets.token_urlsafe(24)
        settings = {'SECRET_KEY': secrets.token_hex(32), 'PUBLIC_ORIGIN': 'http://127.0.0.1:5055',
                    'USERNAME': 'example-viewer', 'PASSWORD_HASH': generate_password_hash(password),
                    'TOKEN_DB': str(local / 'browser-tokens.sqlite'),
                    'B2_BUCKET_ID': cfg['bucket_id'], 'B2_APPLICATION_KEY_ID': cfg['application_key_id'],
                    'B2_APPLICATION_KEY': cfg['application_key'], 'TEST_DISCOVERY_PREFIX': prefix}
        for path, data in ((local / 'browser-app.json', settings),
                           (local / 'browser-login.json', {'username': settings['USERNAME'], 'password': password}),
                           (state_path, {'objects': created, 'entry': movie + 'output.m3u8'})):
            path.write_text(json.dumps(data, indent=2) + '\n')
            path.chmod(0o600)
        success = True
        print('PASS: playable synthetic HLS fixture and private loopback application settings ready.')
        print('Local login is in .local/browser-login.json; no credentials printed.')
        return 0
    except Exception:
        print(f'Browser fixture preparation failed during {stage}; raw details suppressed.', file=sys.stderr)
        return 1
    finally:
        if not success and uploader:
            for item in created:
                try:
                    uploader.delete_file_version(item['id'], item['name'])
                except Exception:
                    print('Synthetic cleanup incomplete; inspect _migration-test/.', file=sys.stderr)


if __name__ == '__main__':
    sys.exit(main())
