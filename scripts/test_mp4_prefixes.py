import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_mp4_prefixes import candidate_names, main, validate_names
from b2_media import MediaAccessError


class PrefixInventoryTests(unittest.TestCase):
    def test_exact_replacement_unicode_case_and_hls_fragments(self):
        self.assertEqual(validate_names(['Year/é.MP4', 'Year/é.MP4', 'Other.mp4',
                                        'Other-extra.txt', 'Movie.hls/init.mp4']), 2)

    def test_non_catalog_sidecar_conflicts_and_unsafe_paths_rejected(self):
        for names in (['Movie.mp4', 'Movie.mp4.notes'], ['Movie.mp4', 'Movie.mp4/secret'],
                      ['../bad.mp4'], ['bad\n.mp4']):
            with self.assertRaises(MediaAccessError):
                validate_names(names)

    def test_combined_upload_inventory_and_sanitized_failure(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            existing = root / 'existing.json'
            source = root / 'Movie.mp4'
            source.write_bytes(b'test')
            existing.write_text(json.dumps([{'fileName': 'Movie.mp4.notes'}]))
            argv = ['--existing', str(existing), '--source', str(source), '--prefix', 'Movie.mp4']
            with patch('builtins.print') as log:
                self.assertEqual(main(argv), 1)
                self.assertNotIn('Movie.mp4', log.call_args.args[0])
            existing.write_text('[]')
            with patch('builtins.print'):
                self.assertEqual(main(argv), 0)
            source.unlink()
            with self.assertRaises(ValueError):
                candidate_names(source, 'Movie.mp4')
            source.mkdir()
            (source / 'init.mp4').write_bytes(b'test')
            (source / '.DS_Store').write_bytes(b'test')
            self.assertEqual(candidate_names(source, 'Movie.hls/'), ['Movie.hls/init.mp4'])
            with self.assertRaises(ValueError):
                candidate_names(source, 'wrong-prefix')


if __name__ == '__main__':
    unittest.main()
