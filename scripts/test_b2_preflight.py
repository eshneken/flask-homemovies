import unittest
import tempfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from b2_preflight import REQUIRED, UnsafeConfiguration, check_private_bucket, load_config, validate_scope


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.scope = {"buckets": [{"id": "test-bucket", "name": "example-media"}],
                      "capabilities": sorted(REQUIRED), "namePrefix": None}

    def test_single_read_key_accepted(self):
        validate_scope(self.scope, "test-bucket")

    def test_read_lifecycle_metadata_accepted(self):
        validate_scope({**self.scope, "capabilities": sorted(REQUIRED | {"readBucketLifecycleRules"})},
                       "test-bucket")

    def test_json_syntax_error_reports_location_without_contents(self):
        directory = Path(__file__).resolve().parents[1] / ".local"
        directory.mkdir(mode=0o700, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=directory) as config:
            config.write('{"example": "sensitive-value"\n"next": "field"}')
            config.flush()
            with self.assertRaises(UnsafeConfiguration) as caught:
                load_config(Path(config.name))
        self.assertIn("line 2", str(caught.exception))
        self.assertNotIn("sensitive-value", str(caught.exception))

    def test_unrestricted_multiple_wrong_and_missing_bucket_denied(self):
        for buckets in (None, [], [{"id": "wrong"}], self.scope["buckets"] * 2):
            with self.subTest(buckets=buckets), self.assertRaises(UnsafeConfiguration):
                validate_scope({**self.scope, "buckets": buckets}, "test-bucket")

    def test_write_admin_unknown_and_all_bucket_listing_denied(self):
        for cap in ("writeFiles", "deleteFiles", "writeBuckets", "writeKeys",
                    "listAllBucketNames", "futureUnknownCapability"):
            with self.subTest(cap=cap), self.assertRaises(UnsafeConfiguration):
                validate_scope({**self.scope, "capabilities": sorted(REQUIRED | {cap})},
                               "test-bucket")

    def test_each_required_capability_checked(self):
        for cap in REQUIRED:
            with self.subTest(cap=cap), self.assertRaises(UnsafeConfiguration):
                validate_scope({**self.scope, "capabilities": sorted(REQUIRED - {cap})},
                               "test-bucket")

    def test_prefix_restriction_denied(self):
        with self.assertRaises(UnsafeConfiguration):
            validate_scope({**self.scope, "namePrefix": "example/"}, "test-bucket")

    def test_public_unknown_missing_and_wrong_bucket_denied(self):
        api = Mock()
        api.account_info.get_allowed.return_value = deepcopy(self.scope)
        for buckets in ([], [SimpleNamespace(id_="wrong", type_="allPrivate")],
                        [SimpleNamespace(id_="test-bucket", type_="allPublic")],
                        [SimpleNamespace(id_="test-bucket", type_="unknown")]):
            api.list_buckets.return_value = buckets
            with self.subTest(buckets=buckets), self.assertRaises(UnsafeConfiguration):
                check_private_bucket(api, "test-bucket")

    def test_bucket_state_is_fresh_and_filtered(self):
        api = Mock()
        api.account_info.get_allowed.return_value = deepcopy(self.scope)
        api.list_buckets.return_value = [SimpleNamespace(id_="test-bucket", type_="allPrivate")]
        check_private_bucket(api, "test-bucket")
        api.list_buckets.assert_called_once_with(bucket_id="test-bucket", use_cache=False)


if __name__ == "__main__":
    unittest.main()
