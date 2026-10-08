#!/usr/bin/env python3
"""Check the loopback synthetic app and B2 CORS without printing bearer URLs."""
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
import requests


def main():
    origin = 'http://127.0.0.1:5055'
    stage = 'synthetic fixture configuration'
    try:
        state = json.loads((Path(__file__).resolve().parents[1] / '.local/browser-test-state.json').read_text())
        assert state['entry'].startswith('_migration-test/')
        client = requests.Session()
        stage = 'authorized page and master playlist'
        page = client.get(origin + '/demo', timeout=30)
        assert page.status_code == 200
        path = html.unescape(re.search(r'<source src="([^"]+)"', page.text)[1])
        master = client.get(origin + path, timeout=30)
        assert master.status_code == 200 and 'no-store' in master.headers['Cache-Control']
        child = next(line for line in master.text.splitlines() if line.startswith('/playlist'))
        stage = 'child playlist and direct B2 media'
        manifest = client.get(origin + child, timeout=30)
        assert manifest.status_code == 200
        media = next(line for line in manifest.text.splitlines() if line.startswith('https://'))
        assert urlsplit(media).hostname.endswith('.backblazeb2.com')
        response = requests.get(media, headers={'Origin': origin}, timeout=30)
        assert response.status_code == 200 and response.headers['Access-Control-Allow-Origin'] == origin
        print('PASS: application master/child playlists and direct B2 media download.')
        stage = 'CORS preflight and unrelated origin'
        response = requests.options(media, headers={'Origin': origin,
            'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'range'}, timeout=30)
        assert response.status_code in (200, 204) and response.headers['Access-Control-Allow-Origin'] == origin
        response = requests.get(media, headers={'Origin': 'https://example.invalid'}, timeout=30)
        assert 'Access-Control-Allow-Origin' not in response.headers
        print('PASS: local-origin Range preflight allowed; unrelated origin receives no CORS grant.')
        stage = 'share creation and guest playlist'
        csrf = re.search(r'"X-CSRF-Token":\s*("[^"]+")', page.text)
        response = client.post(origin + '/share_url', json={'name': state['entry']},
            headers={'X-CSRF-Token': json.loads(csrf[1])}, timeout=30)
        assert response.status_code == 200
        guest = requests.Session()
        page = guest.get(response.json()['url'], timeout=30)
        assert page.status_code == 200
        path = html.unescape(re.search(r'<source src="([^"]+)"', page.text)[1])
        response = guest.get(origin + path, timeout=30)
        assert response.status_code == 200
        child = next(line for line in response.text.splitlines() if line.startswith('/playlist'))
        assert guest.get(origin + child, timeout=30).status_code == 200
        print('PASS: guest share reaches authorized master and child playlists.')
        stage = 'anonymous playlist rejection'
        assert requests.get(origin + '/playlist', params={'entry': state['entry'], 'name': state['entry']}, timeout=30).status_code == 403
        print('PASS: anonymous application playlist rejected.')
        return 0
    except Exception:
        print(f'FAIL during {stage}; raw URLs and credentials suppressed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
