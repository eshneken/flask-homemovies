import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python_app'))
from b2_repository import B2Repository
from b2_policy import REQUIRED
from b2_media import MediaAccessError


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.api = Mock()
        self.api.account_info.get_allowed.return_value = {
            'buckets': [{'id': 'bucket'}], 'capabilities': sorted(REQUIRED), 'namePrefix': None}
        self.bucket = Mock()
        self.bucket.id_, self.bucket.type_ = 'bucket', 'allPrivate'
        self.api.list_buckets.return_value = [self.bucket]
        self.repo = B2Repository(self.api, 'bucket', clock=lambda: self.now)

    def test_discovery_preserves_exact_names_and_excludes_fixtures_and_segments(self):
        names = ['Year/Example é.hls/output.m3u8', 'Year/Example é.hls/segment.ts',
                 '_migration-test/Test.hls/output.m3u8', 'Year/Standalone é.MP4',
                 'Year/Example é.hls/init.mp4', '_migration-test/test.mp4']
        self.bucket.ls.return_value = [(SimpleNamespace(file_name=n), None) for n in names]
        self.assertEqual(self.repo.catalog(), (names[0], names[3]))

    def test_catalog_refreshes_after_five_minutes_without_returning_stale_on_failure(self):
        self.bucket.ls.return_value = [(SimpleNamespace(file_name='Example.hls/output.m3u8'), None)]
        self.repo.catalog()
        self.now = 1299
        self.repo.catalog()
        self.assertEqual(self.bucket.ls.call_count, 1)
        self.now = 1300
        self.bucket.ls.side_effect = RuntimeError('simulated unavailable repository')
        with self.assertRaises(RuntimeError):
            self.repo.catalog()

    def test_small_playlist_range_ends_at_eof(self):
        source = b'#EXTM3U\nsegment.ts\n'
        self.bucket.get_file_info_by_name.return_value = SimpleNamespace(size=len(source))
        download = Mock()
        download.save.side_effect = lambda buffer: buffer.write(source)
        self.bucket.download_file_by_name.return_value = download
        self.assertEqual(self.repo.playlist('Example.hls/output.m3u8', 'Example.hls/'), source.decode())
        self.bucket.download_file_by_name.assert_called_once_with(
            'Example.hls/output.m3u8', range_=(0, len(source) - 1))

    def test_large_and_empty_playlist_denied_before_download(self):
        for size in (0, 1024 * 1024 + 1):
            self.bucket.get_file_info_by_name.return_value = SimpleNamespace(size=size)
            with self.assertRaises(MediaAccessError):
                self.repo.playlist('Example.hls/output.m3u8', 'Example.hls/')
        self.bucket.download_file_by_name.assert_not_called()


if __name__ == '__main__':
    unittest.main()
