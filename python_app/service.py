"""Authenticated movie catalog, sharing and direct private B2 playback."""
import secrets
import sqlite3
import threading
import time
from functools import wraps
from types import SimpleNamespace
from urllib.parse import urlsplit

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, session, url_for
from flask_qrcode import QRcode
from werkzeug.security import check_password_hash
from werkzeug.exceptions import HTTPException

from b2_media import MediaAccessError, movie_prefix, rewrite_manifest, media_kind, movie_title
from b2_policy import UnsafeConfiguration
from cache import TokenStore


def create_app(settings, repository, token_store=None, clock=time.time):
    """Build Flask routes around private media access and expiring SQLite tokens.

    Settings supply login credentials, origin and database path. The injected
    repository and clock let tests exercise authorization without cloud access.
    """
    app = Flask(__name__)
    if len(settings['SECRET_KEY']) < 32:
        raise ValueError('A persistent random session secret is required.')
    origin = urlsplit(settings['PUBLIC_ORIGIN'])
    local = origin.scheme == 'http' and origin.hostname == '127.0.0.1'
    if origin.path or origin.query or origin.fragment or origin.username or not origin.hostname or (origin.scheme != 'https' and not local):
        raise ValueError('PUBLIC_ORIGIN must be an HTTPS origin, or the loopback test origin.')
    app.config.update(SECRET_KEY=settings['SECRET_KEY'], SESSION_COOKIE_SECURE=not local,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      TRUSTED_HOSTS=[origin.hostname], MAX_CONTENT_LENGTH=16 * 1024)
    app.config.update(TESTING=settings.get('TESTING', False))
    store = token_store or TokenStore(settings['TOKEN_DB'], clock)
    app.extensions.update(token_store=store, media_repository=repository)
    QRcode(app)

    def csrf():
        """Create or reuse the CSRF token associated with this browser session."""
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return session['csrf']

    def login_record():
        """Look up the current browser session and enforce its server-side deadline."""
        return store.get(session.get('login_token'), 'session')

    def require_login(view):
        """Decorate a view with a live server-side session check."""
        @wraps(view)
        def wrapped(*args, **kwargs):
            """Redirect unauthenticated callers before invoking the protected view."""
            if not login_record():
                return redirect(url_for('login'))
            return view(*args, **kwargs)
        return wrapped

    def establish_login():
        """Revoke the previous login, rotate browser state and issue a two-hour session."""
        old = session.get('login_token')
        if old:
            store.delete(old)
        session.clear()
        session['login_token'] = store.issue('session', {}, 7200)
        csrf()

    def valid_password():
        """Check submitted credentials using constant-time username and hashed password checks."""
        return (secrets.compare_digest(request.form.get('username', '').encode(), settings['USERNAME'].encode())
                and check_password_hash(settings['PASSWORD_HASH'], request.form.get('password', '')))

    @app.before_request
    def protect_posts():
        """Reject POST requests without a CSRF token matching browser session state."""
        if request.method == 'POST':
            provided = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            if not session.get('csrf') or not secrets.compare_digest(provided.encode(), session['csrf'].encode()):
                abort(403)

    @app.after_request
    def private_response(response):
        """Prevent caching and referrer leakage of private pages and bearer URLs."""
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.context_processor
    def context():
        """Expose the browser CSRF token and current login state to templates."""
        return {'csrf_token': csrf(), 'current_user': SimpleNamespace(is_authenticated=bool(login_record()))}

    @app.errorhandler(sqlite3.Error)
    def database_unavailable(error):
        """Return a sanitized service error when token storage is unavailable."""
        return 'Authentication temporarily unavailable.', 503

    @app.errorhandler(MediaAccessError)
    @app.errorhandler(UnsafeConfiguration)
    def invalid_media(error):
        """Deny unsafe media requests without exposing B2 or configuration details."""
        return 'Unable to access this movie.', 403

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Authenticate a password POST or render a fresh browser-owned QR challenge."""
        if request.method == 'POST':
            if not valid_password():
                return 'Invalid login.', 401
            establish_login()
            return redirect(url_for('home'))
        owner = session.setdefault('qr_owner', secrets.token_urlsafe(32))
        previous = session.get('qr_token')
        if previous:
            store.delete(previous)
        token = store.issue('qr', {'owner': owner, 'approved': False}, 900)
        session['qr_token'] = token
        target = settings['PUBLIC_ORIGIN'] + url_for('authenticate', session_id=token)
        return render_template('login.html', target_url=target, session_id=token)

    @app.route('/authenticate', methods=['GET', 'POST'])
    def authenticate():
        """Render the QR approval form or approve it after verifying credentials."""
        token = request.values.get('session_id', '')
        if not store.get(token, 'qr'):
            abort(403)
        if request.method == 'POST':
            if not valid_password() or not store.approve_qr(token):
                abort(403)
            return render_template('auth_result.html', result='Success. Your viewing device should refresh momentarily.')
        return render_template('auth.html', session_id=token)

    @app.route('/check_auth', methods=['POST'])
    def check_auth():
        """Consume this browser's approved QR challenge and establish a login once."""
        token = (request.get_json(silent=True) or {}).get('session_id', '')
        approved = (isinstance(token, str) and token == session.get('qr_token')
                    and store.consume_qr(token, session.get('qr_owner', '')))
        if approved:
            establish_login()
        return jsonify(is_authenticated=bool(approved))

    @app.route('/logout', methods=['POST'])
    def logout():
        """Revoke the server-side login token and clear browser session state."""
        if session.get('login_token'):
            store.delete(session['login_token'])
        session.clear()
        return redirect(url_for('login'))

    @app.route('/')
    @require_login
    def home():
        """Render catalog entries grouped by folder, preserving exact object names."""
        try:
            names = repository.catalog()
        except Exception:
            return 'Video repository temporarily unavailable.', 503
        sections = {}
        for name in names:
            section = name.split('/', 1)[0] if '/' in name.removesuffix('.hls/output.m3u8') else 'Movies'
            title = movie_title(name)
            sections.setdefault(section, []).append({'name': name, 'display_name': title})
        tab = request.args.get('tab', session.get('active_tab'))
        if tab not in sections:
            tab = next(iter(sections), None)
        session['active_tab'] = tab
        return render_template('home.html', sections=sections, section_objects=sections.get(tab, []))

    def valid_entry(name):
        """Require an exact current catalog entry with a supported media type."""
        if not isinstance(name, str) or name not in repository.catalog():
            abort(404)
        media_kind(name)
        return name

    def player(entry, share=None):
        """Render a movie player using authenticated playlist or MP4 application routes."""
        kind = media_kind(entry)
        url = url_for('playlist' if kind == 'hls' else 'mp4', name=entry, entry=entry,
                      **({'share': share} if share else {}))
        return render_template('shared.html' if share else 'detail.html', par_url=url,
                               video_name=movie_title(entry), full_name=entry,
                               encoding_type='application/x-mpegURL' if kind == 'hls' else 'video/mp4')

    @app.route('/movie')
    @require_login
    def detail():
        """Render the selected catalog movie for a logged-in viewer."""
        return player(valid_entry(request.args.get('name')))

    @app.route('/share_url', methods=['POST'])
    @require_login
    def share_url():
        """Issue a 48-hour share token scoped to exactly one catalog entry."""
        name = valid_entry((request.get_json(silent=True) or {}).get('name'))
        token = store.issue('share', {'entry': name}, 48 * 3600)
        return jsonify(url=settings['PUBLIC_ORIGIN'] + url_for('shared', auth_code=token))

    @app.route('/shared')
    def shared():
        """Render a movie only while its share token is valid."""
        token = request.args.get('auth_code', '')
        record = store.get(token, 'share')
        if not record:
            abort(403)
        return player(valid_entry(record['payload']['entry']), token)

    @app.route('/mp4')
    def mp4():
        """Authorize one MP4, recheck the parent after B2 I/O and redirect to B2.

        An explicit invalid share token never falls back to a logged-in session.
        """
        share = request.args.get('share')
        entry = request.args.get('entry')
        parent = store.get(share, 'share') if share is not None else login_record()
        if not parent or (share is not None and parent['payload']['entry'] != entry):
            abort(403)
        valid_entry(entry)
        if media_kind(entry) != 'mp4':
            abort(403)
        try:
            media, grant = repository.grant(entry, parent['expires_at'])
            live = store.get(share, 'share') if share is not None else login_record()
            if not live:
                abort(403)
            return redirect(media.media_url(repository.bucket, entry, grant), code=302)
        except (MediaAccessError, UnsafeConfiguration, HTTPException):
            raise
        except Exception:
            return 'Video repository temporarily unavailable.', 503

    @app.route('/playlist')
    def playlist():
        """Authorize and rewrite an HLS playlist without proxying media bytes.

        Child playlists retain application authorization; segments, keys and
        other media use B2 grants bounded by the session or share deadline.
        """
        share = request.args.get('share')
        entry = request.args.get('entry')
        # An explicitly supplied invalid share never falls back to a logged-in session.
        parent = store.get(share, 'share') if share is not None else login_record()
        if not parent:
            abort(403)
        if share is not None and parent['payload']['entry'] != entry:
            abort(403)
        valid_entry(entry)
        name = request.args.get('name', entry)
        prefix = movie_prefix(entry)
        if (not name.startswith(prefix) or any(p in ('', '.', '..') for p in name.split('/'))
                or not name.endswith('.m3u8') or '\\' in name):
            abort(403)
        try:
            media, grant = repository.grant(entry, parent['expires_at'])
            source = repository.playlist(name, prefix)
            # Recheck the parent after remote I/O, before exposing bearer URLs.
            live = store.get(share, 'share') if share is not None else login_record()
            if not live:
                abort(403)
            rewritten = rewrite_manifest(source, name, prefix,
                lambda obj: media.media_url(repository.bucket, obj, grant),
                lambda obj: url_for('playlist', name=obj, entry=entry,
                                    **({'share': share} if share is not None else {})))
            return Response(rewritten, content_type='application/vnd.apple.mpegurl')
        except (MediaAccessError, UnsafeConfiguration, HTTPException):
            raise
        except Exception:
            return 'Video repository temporarily unavailable.', 503

    @app.route('/health')
    def health():
        """Report that the Flask process can respond without querying cloud dependencies."""
        return 'ok'

    if settings.get('START_CLEANUP', True):
        def cleanup_loop():
            """Reap expired tokens every minute; request-time expiry remains authoritative."""
            while True:
                time.sleep(60)
                try:
                    store.cleanup()
                except sqlite3.Error:
                    pass  # Authorization still checks expiry; full/busy DB fails closed.
        threading.Thread(target=cleanup_loop, daemon=True, name='token-cleanup').start()
    return app
