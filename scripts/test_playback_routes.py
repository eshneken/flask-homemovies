import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sqlite3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python_app'))
from b2_media import B2Media
from b2_policy import REQUIRED
from b2_policy import UnsafeConfiguration
from b2_media import MediaAccessError
from cache import TokenStore
from service import create_app
from werkzeug.security import generate_password_hash


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = 1000
        self.store = TokenStore(Path(self.directory.name) / 'tokens.sqlite', clock=lambda: self.now)
        self.entry = 'Example.hls/output.m3u8'
        self.other = 'Other.hls/output.m3u8'
        api = Mock()
        api.account_info.get_allowed.return_value = {'buckets': [{'id': 'bucket'}],
            'capabilities': sorted(REQUIRED), 'namePrefix': None}
        bucket = Mock()
        bucket.id_, bucket.type_ = 'bucket', 'allPrivate'
        bucket.get_download_authorization.return_value = '<test-download-token>'
        bucket.get_download_url.side_effect = lambda name: 'https://example.com/file/media/' + name
        api.list_buckets.return_value = [bucket]
        self.repo = Mock()
        self.repo.catalog.return_value = (self.entry, self.other)
        self.repo.bucket = bucket
        media = B2Media(api, 'bucket', self.repo.catalog(), lambda: self.now)
        self.repo.grant.side_effect = lambda entry, expires: (media, media.grant(entry, expires))
        self.repo.playlist.side_effect = lambda name, prefix: (
            '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nvariant/main.m3u8\n'
            if name.endswith('output.m3u8') else '#EXTM3U\n#EXTINF:2,\n../seg.ts\n')
        self.app = create_app({'SECRET_KEY': '<test-only>' * 6, 'PUBLIC_ORIGIN': 'http://127.0.0.1:5055',
                              'USERNAME': 'example-viewer', 'PASSWORD_HASH': generate_password_hash('<test-only>'),
                              'TOKEN_DB': str(Path(self.directory.name) / 'tokens.sqlite'),
                              'TESTING': True, 'START_CLEANUP': False}, self.repo, self.store, lambda: self.now)
        self.app.config['SERVER_NAME'] = '127.0.0.1:5055'
        self.client = self.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def session_login(self, ttl=100):
        token = self.store.issue('session', {}, ttl)
        with self.client.session_transaction() as s:
            s['login_token'] = token
        return token

    def playlist_url(self, **kwargs):
        return '/playlist', {'entry': self.entry, 'name': self.entry, **kwargs}

    def test_anonymous_playlist_denied_without_b2_request(self):
        path, args = self.playlist_url()
        self.assertEqual(self.client.get(path, query_string=args).status_code, 403)
        self.repo.grant.assert_not_called()

    def test_master_child_and_direct_media_routes(self):
        self.session_login()
        path, args = self.playlist_url()
        response = self.client.get(path, query_string=args)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        self.assertIn('no-store', response.headers['Cache-Control'])
        child = next(line for line in response.text.splitlines() if line.startswith('/playlist'))
        response = self.client.get(child)
        self.assertEqual(response.status_code, 200)
        self.assertIn('https://example.com/file/media/Example.hls/seg.ts?Authorization=', response.text)

    def test_session_expiry_boundary_enforced_without_cleanup(self):
        self.session_login(ttl=100)
        path, args = self.playlist_url()
        self.now = 1090
        self.assertEqual(self.client.get(path, query_string=args).status_code, 200)
        self.now = 1100
        self.assertEqual(self.client.get(path, query_string=args).status_code, 403)

    def test_share_children_and_cross_movie_denial(self):
        token = self.store.issue('share', {'entry': self.entry}, 100)
        path, args = self.playlist_url(share=token)
        response = self.client.get(path, query_string=args)
        self.assertEqual(response.status_code, 200)
        child = next(line for line in response.text.splitlines() if line.startswith('/playlist'))
        self.assertIn('share=', child)
        self.assertEqual(self.client.get(child).status_code, 200)
        self.assertEqual(self.client.get(path, query_string={'entry': self.other, 'name': self.other, 'share': token}).status_code, 403)
        self.now = 1100
        self.assertEqual(self.client.get(child).status_code, 403)

    def test_invalid_share_does_not_fall_back_to_session(self):
        self.session_login()
        path, args = self.playlist_url(share='invalid')
        self.assertEqual(self.client.get(path, query_string=args).status_code, 403)

    def test_cross_prefix_and_traversal_denied(self):
        self.session_login()
        for name in ('Other.hls/output.m3u8', 'Example.hls/../Other.hls/output.m3u8', 'Example.hls-extra/output.m3u8'):
            with self.subTest(name=name):
                self.assertEqual(self.client.get('/playlist', query_string={'entry': self.entry, 'name': name}).status_code, 403)
        self.repo.playlist.assert_not_called()

    def test_expiry_during_remote_io_denied(self):
        self.session_login(ttl=100)
        def slow_playlist(*args):
            self.now = 1100
            return '#EXTM3U\nseg.ts\n'
        self.repo.playlist.side_effect = slow_playlist
        path, args = self.playlist_url()
        self.assertEqual(self.client.get(path, query_string=args).status_code, 403)

    def test_csrf_and_login_and_logout(self):
        self.client.get('/login')
        with self.client.session_transaction() as s:
            csrf = s['csrf']
        self.assertEqual(self.client.post('/login', data={'username': 'example-viewer', 'password': '<test-only>'}).status_code, 403)
        response = self.client.post('/login', data={'username': 'example-viewer', 'password': '<test-only>', 'csrf_token': csrf})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as s:
            token, csrf = s['login_token'], s['csrf']
        self.assertIsNotNone(self.store.get(token, 'session'))
        self.assertEqual(self.client.post('/logout', data={'csrf_token': csrf}).status_code, 302)
        self.assertIsNone(self.store.get(token, 'session'))

    def test_empty_library_renders(self):
        self.session_login()
        self.repo.catalog.return_value = ()
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_qr_approval_cannot_be_consumed_from_other_browser(self):
        self.client.get('/login')
        with self.client.session_transaction() as s:
            token, viewer_csrf = s['qr_token'], s['csrf']
        phone = self.app.test_client()
        self.assertEqual(phone.get('/authenticate', query_string={'session_id': token}).status_code, 200)
        with phone.session_transaction() as s:
            phone_csrf = s['csrf']
        self.assertEqual(phone.post('/authenticate', data={'session_id': token,
            'username': 'example-viewer', 'password': '<test-only>', 'csrf_token': phone_csrf}).status_code, 200)
        wrong = phone.post('/check_auth', json={'session_id': token}, headers={'X-CSRF-Token': phone_csrf})
        self.assertFalse(wrong.json['is_authenticated'])
        correct = self.client.post('/check_auth', json={'session_id': token}, headers={'X-CSRF-Token': viewer_csrf})
        self.assertTrue(correct.json['is_authenticated'])
        self.assertIsNone(self.store.get(token, 'qr'))

    def test_untrusted_host_rejected(self):
        self.assertEqual(self.client.get('/health', headers={'Host': 'example.invalid'}).status_code, 400)

    def test_health_login_redirect_and_invalid_login(self):
        self.assertEqual(self.client.get('/health').text, 'ok')
        self.assertEqual(self.client.get('/').status_code, 302)
        self.client.get('/login')
        with self.client.session_transaction() as s:
            csrf = s['csrf']
        self.assertEqual(self.client.post('/login', data={'username': 'example-viewer',
            'password': '<incorrect>', 'csrf_token': csrf}).status_code, 401)

    def test_library_sections_and_repository_failure(self):
        self.session_login()
        self.repo.catalog.return_value = ('Year/Example.hls/output.m3u8',)
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Year', page.text)
        self.assertIn('Example', page.text)
        self.repo.catalog.side_effect = RuntimeError('simulated repository failure')
        self.assertEqual(self.client.get('/').status_code, 503)

    def test_movie_catalog_selection_and_share_creation(self):
        self.session_login()
        self.assertEqual(self.client.get('/movie', query_string={'name': self.entry}).status_code, 200)
        self.assertEqual(self.client.get('/movie', query_string={'name': 'Unknown.hls/output.m3u8'}).status_code, 404)
        with self.client.session_transaction() as s:
            s['csrf'] = '<test-csrf>'
        response = self.client.post('/share_url', json={'name': self.entry}, headers={'X-CSRF-Token': '<test-csrf>'})
        self.assertEqual(response.status_code, 200)
        from urllib.parse import urlsplit, parse_qs
        token = parse_qs(urlsplit(response.json['url']).query)['auth_code'][0]
        record = self.store.get(token, 'share')
        self.assertEqual(record['expires_at'], self.now + 48 * 3600)
        self.assertEqual(record['payload']['entry'], self.entry)
        guest = self.app.test_client()
        self.assertEqual(guest.get(response.json['url']).status_code, 200)
        self.assertEqual(guest.get('/shared', query_string={'auth_code': 'invalid'}).status_code, 403)

    def test_full_database_denies_login_and_media_errors_are_sanitized(self):
        from unittest.mock import patch
        with patch.object(self.store, 'issue', side_effect=sqlite3.OperationalError('database is full')):
            self.assertEqual(self.client.get('/login').status_code, 503)
        self.session_login()
        path, args = self.playlist_url()
        for exception, status in ((MediaAccessError('<private-detail>'), 403),
                                  (UnsafeConfiguration('<private-detail>'), 403),
                                  (RuntimeError('<private-detail>'), 503)):
            with self.subTest(exception=type(exception).__name__):
                self.repo.grant.side_effect = exception
                response = self.client.get(path, query_string=args)
                self.assertEqual(response.status_code, status)
                self.assertNotIn('private-detail', response.text)

    def test_qr_revisit_removes_old_challenge_and_invalid_approval_denied(self):
        self.client.get('/login')
        with self.client.session_transaction() as s:
            old = s['qr_token']
        self.client.get('/login')
        self.assertIsNone(self.store.get(old, 'qr'))
        self.assertEqual(self.client.get('/authenticate', query_string={'session_id': old}).status_code, 403)
        with self.client.session_transaction() as s:
            new, csrf = s['qr_token'], s['csrf']
        self.assertEqual(self.client.post('/authenticate', data={'session_id': new,
            'username': 'example-viewer', 'password': '<incorrect>', 'csrf_token': csrf}).status_code, 403)

    def test_repeat_login_revokes_previous_session(self):
        old = self.session_login()
        with self.client.session_transaction() as s:
            s['csrf'] = '<test-csrf>'
        self.assertEqual(self.client.post('/login', data={'username': 'example-viewer',
            'password': '<test-only>', 'csrf_token': '<test-csrf>'}).status_code, 302)
        self.assertIsNone(self.store.get(old, 'session'))

    def test_configuration_rejects_weak_secret_and_non_https_production_origin(self):
        base = {'SECRET_KEY': '<test-only>' * 6, 'PUBLIC_ORIGIN': 'http://127.0.0.1:5055'}
        for change in ({'SECRET_KEY': '<short>'}, {'PUBLIC_ORIGIN': 'http://example.com'},
                       {'PUBLIC_ORIGIN': 'https://example.com/path'}):
            with self.assertRaises(ValueError):
                create_app({**base, **change}, self.repo, self.store)


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'tokens.sqlite'
        self.now = 1000
        self.store = TokenStore(self.path, clock=lambda: self.now)

    def tearDown(self):
        self.directory.cleanup()

    def test_expiry_survives_restart_and_does_not_depend_on_cleanup(self):
        token = self.store.issue('share', {'entry': 'Example.hls/output.m3u8'}, 100)
        self.now = 1099.999
        self.assertIsNotNone(self.store.get(token, 'share'))
        reopened = TokenStore(self.path, clock=lambda: self.now)
        self.now = 1100
        self.assertIsNone(reopened.get(token, 'share'))
        with reopened.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tokens').fetchone()[0], 1)
        reopened.cleanup()
        with reopened.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tokens').fetchone()[0], 0)

    def test_qr_approval_and_polling_never_extend_expiry(self):
        token = self.store.issue('qr', {'owner': 'bound-browser', 'approved': False}, 900)
        before = self.store.get(token, 'qr')['expires_at']
        self.now = 1800
        self.assertTrue(self.store.approve_qr(token))
        self.assertEqual(self.store.get(token, 'qr')['expires_at'], before)
        self.assertFalse(self.store.consume_qr(token, 'different-browser'))
        self.now = 1900
        self.assertFalse(self.store.consume_qr(token, 'bound-browser'))

    def test_qr_consumption_atomic_and_single_use(self):
        token = self.store.issue('qr', {'owner': 'bound-browser', 'approved': False}, 900)
        self.store.approve_qr(token)
        with ThreadPoolExecutor(max_workers=4) as executor:
            winners = list(executor.map(lambda _: self.store.consume_qr(token, 'bound-browser'), range(4)))
        self.assertEqual(sum(winners), 1)

    def test_capacity_enforced_and_cleanup_reclaims_space(self):
        store = TokenStore(self.path, clock=lambda: self.now, max_bytes=64 * 1024)
        with self.assertRaises(sqlite3.OperationalError):
            for _ in range(100):
                store.issue('share', {'value': 'x' * 5000}, 1)
        self.assertLessEqual(self.path.stat().st_size, 64 * 1024)
        self.now += 2
        store.cleanup()
        self.assertIsNotNone(store.issue('share', {}, 1))


if __name__ == '__main__':
    unittest.main()
