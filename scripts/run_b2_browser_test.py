#!/usr/bin/env python3
"""Loopback-only synthetic demo. Never use this launcher for production."""
import json
import os
import sys
from pathlib import Path
from flask import redirect, session, url_for

root = Path(__file__).resolve().parents[1]
os.environ['HM_CONFIG_FILE'] = str(root / '.local/browser-app.json')
sys.path.insert(0, str(root / 'python_app'))
from app import create_runtime_app

settings = json.loads((root / '.local/browser-app.json').read_text())
state = json.loads((root / '.local/browser-test-state.json').read_text())
if (settings['PUBLIC_ORIGIN'] != 'http://127.0.0.1:5055'
        or not settings.get('TEST_DISCOVERY_PREFIX', '').startswith('_migration-test/')
        or not state['entry'].startswith(settings['TEST_DISCOVERY_PREFIX'])):
    raise SystemExit('Synthetic loopback fixture scope is invalid.')
app = create_runtime_app()


@app.route('/demo')
def demo():
    # Local convenience entry point applies only to the synthetic-prefix app instance.
    session.clear()
    session['login_token'] = app.extensions['token_store'].issue('session', {}, 7200)
    return redirect(url_for('detail', name=state['entry']))


app.run(host='127.0.0.1', port=5055, debug=False)
