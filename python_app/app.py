"""Gunicorn application factory; settings come from OCI Vault or ignored local JSON."""
import base64
import json
import logging
import os
from pathlib import Path

from b2sdk.v3 import B2Api, InMemoryAccountInfo
from b2_repository import B2Repository
from service import create_app


def create_runtime_app():
    # SDK diagnostic logs can include bearer URLs. Never enable SDK wire logging.
    logging.getLogger('b2sdk').disabled = True
    logging.getLogger('werkzeug').disabled = True
    try:
        local_file = os.environ.get('HM_CONFIG_FILE')
        if local_file:
            path = Path(local_file)
            if path.stat().st_mode & 0o077:
                raise ValueError('Local settings require owner-only file permissions.')
            settings = json.loads(path.read_text())
        else:
            import oci
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            client = oci.secrets.SecretsClient({'region': signer.region}, signer=signer)
            bundle = client.get_secret_bundle(os.environ['HM_CONFIG_SECRET_OCID']).data
            settings = json.loads(base64.b64decode(bundle.secret_bundle_content.content).decode('utf-8'))
        api = B2Api(InMemoryAccountInfo())
        api.authorize_account(settings['B2_APPLICATION_KEY_ID'], settings['B2_APPLICATION_KEY'])
        repository = B2Repository(api, settings['B2_BUCKET_ID'],
                                  discovery_prefix=settings.get('CATALOG_PREFIX', ''))
        return create_app(settings, repository)
    except Exception:
        raise RuntimeError('Application initialization failed; verify private settings and service access. Raw details suppressed.') from None


if __name__ == '__main__':
    create_runtime_app().run(host='127.0.0.1', port=5055, debug=False)
