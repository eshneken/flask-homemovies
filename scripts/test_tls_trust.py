"""Exercise installed TLS stores, including pip's independent vendored bundle."""
import ssl
import unittest
from importlib.metadata import version

import certifi
from pip._vendor import certifi as pip_certifi


class TlsTrustTests(unittest.TestCase):
    def test_installed_packages_include_emsign_remediation(self):
        self.assertGreaterEqual(tuple(map(int, version('pip').split('.'))), (26, 2, 2))
        self.assertGreaterEqual(tuple(map(int, certifi.__version__.split('.'))), (2026, 10, 19))

    def test_system_application_and_installer_stores_exclude_affected_roots(self):
        # Value: protects=TLS trust across independent stores; fails_when=affected roots return;
        # why_new=application mocks never exercise installed trust; seam=none;
        # no_claim=deployed VM and container are checked separately during maintenance.
        affected = {'AAA Certificate Services', 'emSign ECC Root CA - G3'}
        for label, bundle in [('system', None), ('application', certifi.where()),
                              ('pip', pip_certifi.where())]:
            with self.subTest(store=label):
                roots = ssl.create_default_context(cafile=bundle).get_ca_certs()
                self.assertTrue(roots, 'A usable CA store must remain installed')
                names = {value for root in roots for part in root['subject']
                         for key, value in part if key == 'commonName'}
                self.assertFalse(affected & names)
