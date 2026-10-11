import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import mask_configuration as configuration
from oci_wif import WifError


class ConfigurationMaskTests(unittest.TestCase):
    def test_mask_all_values_before_use(self):
        with patch.object(configuration,'mask') as mask:
            configuration.configure('["test-tenancy", "test-user", "test-private-host"]')
        self.assertEqual([c.args[0] for c in mask.call_args_list],['test-tenancy','test-user','test-private-host'])

    def test_reject_partial_malformed_masks_without_emitting_values(self):
        for value in ('[]','{}','["test-private",null]','[""]'):
            with patch.object(configuration,'mask') as mask, self.assertRaises(WifError):
                configuration.configure(value)
            mask.assert_not_called()

    def test_main_suppresses_raw_failures(self):
        with patch.dict(configuration.os.environ,{'OCI_PRIVATE_CONFIG_MASKS':'["test-private"]'}),patch.object(configuration,'mask'):
            self.assertEqual(configuration.main(),0)
        with patch.dict(configuration.os.environ,{},clear=True),patch('builtins.print') as output:
            self.assertEqual(configuration.main(),1)
            self.assertNotIn('test-private',output.call_args.args[0])
