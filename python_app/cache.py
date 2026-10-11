"""Disposable SQLite authentication tokens with enforced expiry and bounded storage."""
import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager


class TokenStore:
    def __init__(self, path, clock=time.time, max_bytes=32 * 1024 * 1024):
        self.path = str(path)
        self.clock = clock
        self.max_bytes = max_bytes
        Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA auto_vacuum=INCREMENTAL')
            size = db.execute('PRAGMA page_size').fetchone()[0]
            db.execute(f'PRAGMA max_page_count={max(16, max_bytes // size)}')
            db.execute('CREATE TABLE IF NOT EXISTS tokens (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS token_expiry ON tokens(expires)')
        Path(path).chmod(0o600)
        self.cleanup()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute('PRAGMA journal_mode=DELETE')
            size = db.execute('PRAGMA page_size').fetchone()[0]
            db.execute(f'PRAGMA max_page_count={max(16, self.max_bytes // size)}')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def issue(self, kind, payload, ttl):
        token = secrets.token_urlsafe(32)
        expiry = self.clock() + ttl
        with self.connect() as db:
            db.execute('INSERT INTO tokens VALUES (?, ?, ?, ?)',
                       (self.digest(token), kind, json.dumps(payload), expiry))
        return token

    def get(self, token, kind):
        if not isinstance(token, str) or len(token) > 200:
            return None
        with self.connect() as db:
            row = db.execute('SELECT payload, expires FROM tokens WHERE id=? AND kind=? AND expires>?',
                             (self.digest(token), kind, self.clock())).fetchone()
        return {'payload': json.loads(row[0]), 'expires_at': row[1]} if row else None

    def delete(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM tokens WHERE id=?', (self.digest(token),))

    def approve_qr(self, token):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM tokens WHERE id=? AND kind=? AND expires>?',
                             (self.digest(token), 'qr', self.clock())).fetchone()
            if not row:
                return False
            payload = json.loads(row[0])
            payload['approved'] = True
            db.execute('UPDATE tokens SET payload=? WHERE id=?', (json.dumps(payload), self.digest(token)))
            return True

    def consume_qr(self, token, owner):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM tokens WHERE id=? AND kind=? AND expires>?',
                             (self.digest(token), 'qr', self.clock())).fetchone()
            if not row:
                return False
            payload = json.loads(row[0])
            if not payload.get('approved') or not secrets.compare_digest(payload['owner'], owner):
                return False
            db.execute('DELETE FROM tokens WHERE id=?', (self.digest(token),))
            return True

    def cleanup(self):
        with self.connect() as db:
            db.execute('DELETE FROM tokens WHERE expires<=?', (self.clock(),))
            db.execute('PRAGMA incremental_vacuum(64)')
