import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python_app'))
from b2_media import B2Media, MediaAccessError, movie_prefix, rewrite_manifest, media_kind, movie_title
from b2_policy import REQUIRED


class ManifestTests(unittest.TestCase):
    prefix = 'Example Movie.hls/'
    playlist = prefix + 'output.m3u8'

    def rewrite(self, text, playlist=None):
        return rewrite_manifest(text, playlist or self.playlist, self.prefix,
                                lambda n: 'MEDIA:' + n, lambda n: 'PLAYLIST:' + n)

    def test_nested_playlists_media_keys_maps_and_subtitles(self):
        source = ('#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,URI="subs/sub.m3u8"\n'
                  '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n'
                  '#EXT-X-MAP:URI="init.mp4",BYTERANGE="20@0"\n'
                  '#EXT-X-STREAM-INF:BANDWIDTH=1000\nvariant/main.m3u8\n'
                  '#EXTINF:2,\nsegment%20%C3%A9.ts\n')
        result = self.rewrite(source)
        for path in ('subs/sub.m3u8', 'variant/main.m3u8'):
            self.assertIn('PLAYLIST:' + self.prefix + path, result)
        for path in ('key.bin', 'init.mp4', 'segment é.ts'):
            self.assertIn('MEDIA:' + self.prefix + path, result)
        self.assertIn('BYTERANGE="20@0"', result)

    def test_relative_parent_inside_movie_allowed(self):
        self.assertIn('MEDIA:' + self.prefix + 'seg.ts',
                      self.rewrite('#EXTM3U\n../seg.ts\n', self.prefix + 'variant/main.m3u8'))

    def test_external_absolute_query_fragment_and_escape_denied(self):
        for uri in ('https://example.com/seg.ts', '//example.com/x', '/absolute.ts',
                    '../other.hls/seg.ts', '%2e%2e/other.ts', 'seg.ts?token=x',
                    'seg.ts#fragment', 'dir\\seg.ts', '%00.ts'):
            with self.subTest(uri=uri), self.assertRaises(MediaAccessError):
                self.rewrite('#EXTM3U\n' + uri + '\n')

    def test_unquoted_uri_and_non_playlist_denied(self):
        for source in ('not HLS', '#EXTM3U\n#EXT-X-KEY:URI=key.bin\n',
                       '#EXTM3U\n#EXT-X-CONTENT-STEERING:SERVER-URI="https://example.com"\n',
                       '#EXTM3U\n#EXT-X-DEFINE:NAME="variable",VALUE="example"\n'):
            with self.assertRaises(MediaAccessError):
                self.rewrite(source)

    def test_catalog_prefix_requires_exact_hls_directory(self):
        self.assertEqual(movie_prefix(self.playlist), self.prefix)
        for entry in ('output.m3u8', 'year/output.m3u8', '../Example.hls/output.m3u8'):
            with self.assertRaises(MediaAccessError):
                movie_prefix(entry)


class GrantTests(unittest.TestCase):
    def test_mp4_type_and_title_preserve_unicode_and_reject_hls_segments(self):
        self.assertEqual(media_kind('Year/Example é.MP4'), 'mp4')
        self.assertEqual(movie_title('Year/Example é.MP4'), 'Example é')
        for entry in ('Year/Example.hls/init.mp4', '../bad.mp4', '/bad.mp4', 'bad\n.mp4', 'bad\\name.mp4', 'bad.txt', None):
            with self.subTest(entry=entry), self.assertRaises(MediaAccessError):
                media_kind(entry)

    def test_mp4_native_grant_checks_entire_filename_prefix_and_exact_url(self):
        entry = 'Year/Example é.mp4'
        media = B2Media(self.api, 'bucket', [entry], clock=lambda: self.now)
        self.api.session.list_file_names.return_value = {'files': [{'fileName': entry}], 'nextFileName': None}
        grant = media.grant(entry, 1040)
        self.assertEqual(grant.exact_name, entry)
        self.bucket.get_download_authorization.assert_called_once_with(entry, 35)
        self.assertEqual(self.api.session.list_file_names.call_count, 2)
        media.media_url(self.bucket, entry, grant)
        with self.assertRaises(MediaAccessError):
            media.media_url(self.bucket, entry + '.extra', grant)

    def test_mp4_missing_collision_hidden_non_catalog_and_listing_failure_fail_closed(self):
        entry = 'Example.mp4'
        media = B2Media(self.api, 'bucket', [entry], clock=lambda: self.now)
        for listing in ({'files': []}, {'files': [{'fileName': entry}, {'fileName': entry + '.notes'}]},
                        {'files': [{'fileName': entry}], 'nextFileName': entry + '.extra'}):
            self.api.session.list_file_names.return_value = listing
            with self.assertRaises(MediaAccessError):
                media.grant(entry, 2000)
        self.bucket.get_download_authorization.assert_not_called()
        self.api.session.list_file_names.side_effect = RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            media.grant(entry, 2000)

    def test_mp4_collision_appearing_during_grant_prevents_url_release(self):
        entry = 'Example.mp4'
        media = B2Media(self.api, 'bucket', [entry], clock=lambda: self.now)
        self.api.session.list_file_names.side_effect = [
            {'files': [{'fileName': entry}]},
            {'files': [{'fileName': entry}, {'fileName': entry + '.extra'}]}]
        with self.assertRaises(MediaAccessError):
            media.grant(entry, 2000)

    def setUp(self):
        self.now = 1000
        self.api = Mock()
        self.api.account_info.get_allowed.return_value = {
            'buckets': [{'id': 'bucket'}], 'capabilities': sorted(REQUIRED), 'namePrefix': None}
        self.bucket = Mock()
        self.bucket.id_ = 'bucket'
        self.bucket.type_ = 'allPrivate'
        self.bucket.get_download_authorization.return_value = '<synthetic-token>'
        self.bucket.get_download_url.return_value = 'https://example.com/file/example/segment.ts'
        self.api.list_buckets.return_value = [self.bucket]
        self.entry = 'Example.hls/output.m3u8'
        self.media = B2Media(self.api, 'bucket', [self.entry], clock=lambda: self.now)

    def test_parent_deadline_bounds_grant_and_trailing_slash(self):
        grant = self.media.grant(self.entry, 1040.9)
        self.bucket.get_download_authorization.assert_called_once_with('Example.hls/', 35)
        self.assertLess(grant.expires_at, 1040.9)
        self.assertNotIn('<synthetic-token>', repr(grant))

    def test_missing_catalog_and_expired_parent_denied(self):
        for entry, deadline in [('Other.hls/output.m3u8', 2000), (self.entry, 1000),
                                (self.entry, 1005)]:
            with self.assertRaises(MediaAccessError):
                self.media.grant(entry, deadline)
        self.bucket.get_download_authorization.assert_not_called()

    def test_public_bucket_denied_before_grant(self):
        self.bucket.type_ = 'allPublic'
        with self.assertRaises(MediaAccessError):
            self.media.grant(self.entry, 2000)
        self.bucket.get_download_authorization.assert_not_called()

    def test_cross_prefix_sibling_traversal_and_expired_url_denied(self):
        grant = self.media.grant(self.entry, 2000)
        for name in ('Other.hls/segment.ts', 'Example.hls-extra/segment.ts',
                     'Example.hls/../Other.hls/segment.ts'):
            with self.subTest(name=name), self.assertRaises(MediaAccessError):
                self.media.media_url(self.bucket, name, grant)
        self.now = grant.expires_at
        with self.assertRaises(MediaAccessError):
            self.media.media_url(self.bucket, 'Example.hls/segment.ts', grant)

    def test_slow_grant_request_denied(self):
        self.bucket.get_download_authorization.side_effect = lambda *args: setattr(self, 'now', 3000)
        with self.assertRaises(MediaAccessError):
            self.media.grant(self.entry, 2000)

    def test_request_exceeding_skew_budget_denied(self):
        self.bucket.get_download_authorization.side_effect = lambda *args: setattr(self, 'now', 1006)
        with self.assertRaises(MediaAccessError):
            self.media.grant(self.entry, 2000)

    def test_url_works_before_expiry_and_contains_download_token(self):
        grant = self.media.grant(self.entry, 2000)
        self.now = grant.expires_at - 0.001
        self.assertIn('Authorization=', self.media.media_url(self.bucket, 'Example.hls/segment.ts', grant))


if __name__ == '__main__':
    unittest.main()
