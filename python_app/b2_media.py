"""Native B2 media primitives. Authorization is supplied by the application."""

import math
import posixpath
import re
import time
from dataclasses import dataclass, field
from urllib.parse import unquote, urlencode, urlsplit

from b2_policy import validate_scope


class MediaAccessError(ValueError):
    pass


def movie_prefix(entrypoint):
    if (not entrypoint.endswith('.hls/output.m3u8') or entrypoint.startswith('/')
            or any(c in entrypoint for c in ('\\', '\x00', '\r', '\n'))
            or any(p in ('', '.', '..') for p in entrypoint.split('/'))):
        raise MediaAccessError('Invalid catalog HLS entrypoint.')
    return entrypoint.rsplit('/', 1)[0] + '/'


def media_kind(entrypoint):
    if (not isinstance(entrypoint, str) or entrypoint.startswith('/')
            or any(ord(c) < 32 for c in entrypoint) or '\\' in entrypoint
            or any(p in ('', '.', '..') for p in entrypoint.split('/'))):
        raise MediaAccessError('Invalid movie entrypoint.')
    if entrypoint.endswith('.hls/output.m3u8'):
        movie_prefix(entrypoint)
        return 'hls'
    if (entrypoint.lower().endswith('.mp4')
            and not any(p.lower().endswith('.hls') for p in entrypoint.split('/')[:-1])):
        return 'mp4'
    raise MediaAccessError('Unsupported movie entrypoint.')


def movie_title(entrypoint):
    return (movie_prefix(entrypoint).rstrip('/').rsplit('/', 1)[-1][:-4]
            if media_kind(entrypoint) == 'hls' else entrypoint.rsplit('/', 1)[-1][:-4])


def resolve_reference(playlist, reference, prefix):
    if any(ord(c) < 32 for c in reference):
        raise MediaAccessError('Unsafe HLS reference.')
    parts = urlsplit(reference)
    if parts.scheme or parts.netloc or parts.query or parts.fragment or not parts.path:
        raise MediaAccessError('HLS reference must be a relative object path.')
    path = unquote(parts.path, errors='strict')
    if path.startswith('/') or '\\' in path or any(ord(c) < 32 for c in path):
        raise MediaAccessError('Unsafe HLS reference.')
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(playlist), path))
    if not resolved.startswith(prefix) or resolved == prefix.rstrip('/'):
        raise MediaAccessError('HLS reference escapes its movie prefix.')
    return resolved


URI_ATTRIBUTE = re.compile(r'(?P<lead>(?:[:,])URI=)"(?P<uri>[^"\r\n]*)"')


def rewrite_manifest(text, playlist, prefix, media_url, playlist_url):
    """Rewrite media to B2 and child playlists to authenticated application routes."""
    if (not playlist.startswith(prefix) or posixpath.normpath(playlist) != playlist
            or any(ord(c) < 32 for c in playlist)
            or not text.lstrip('\ufeff').startswith('#EXTM3U')):
        raise MediaAccessError('Invalid playlist or movie scope.')

    def rewrite(uri):
        name = resolve_reference(playlist, uri, prefix)
        return playlist_url(name) if name.lower().endswith('.m3u8') else media_url(name)

    result = []
    for line in text.lstrip('\ufeff').splitlines(keepends=True):
        body = line.rstrip('\r\n')
        ending = line[len(body):]
        if body.startswith('#'):
            if body.startswith(('#EXT-X-CONTENT-STEERING:', '#EXT-X-DEFINE:')):
                raise MediaAccessError('Playlist uses an unsupported dynamic URI feature.')
            # Reject malformed/unquoted URI attributes rather than leaving a bypass.
            matches = list(URI_ATTRIBUTE.finditer(body))
            if len(matches) != len(re.findall(r'(?:[:,])URI=', body)):
                raise MediaAccessError('Malformed HLS URI attribute.')
            body = URI_ATTRIBUTE.sub(lambda m: m['lead'] + '"' + rewrite(m['uri']) + '"', body)
        elif body.strip():
            body = rewrite(body)
        result.append(body + ending)
    return ''.join(result)


@dataclass(frozen=True)
class DownloadGrant:
    prefix: str
    expires_at: float
    token: str = field(repr=False)
    exact_name: str | None = None


class B2Media:
    def __init__(self, api, bucket_id, catalog_entrypoints, clock=time.time):
        self.api = api
        self.bucket_id = bucket_id
        self.catalog = frozenset(catalog_entrypoints)
        self.clock = clock

    def grant(self, entrypoint, parent_expires_at, max_seconds=7200):
        if entrypoint not in self.catalog:
            raise MediaAccessError('Movie is not in the authorized catalog.')
        exact_name = entrypoint if media_kind(entrypoint) == 'mp4' else None
        prefix = exact_name or movie_prefix(entrypoint)
        # Reserve five seconds for request latency and clock skew. Never extend parent TTL.
        started = self.clock()
        seconds = math.floor(min(max_seconds, 604800, parent_expires_at - started - 5))
        if seconds < 1:
            raise MediaAccessError('Playback authorization has expired or is too near expiry.')
        validate_scope(self.api.account_info.get_allowed(), self.bucket_id)
        buckets = self.api.list_buckets(bucket_id=self.bucket_id, use_cache=False)
        if len(buckets) != 1 or buckets[0].id_ != self.bucket_id or buckets[0].type_ != 'allPrivate':
            raise MediaAccessError('Private bucket could not be verified.')
        bucket = buckets[0]
        if exact_name:
            self.assert_exact_file(exact_name)
        token = bucket.get_download_authorization(prefix, seconds)
        if exact_name:
            self.assert_exact_file(exact_name)
        expires = started + seconds
        finished = self.clock()
        if finished >= expires or finished - started > 5:
            raise MediaAccessError('Download grant request exceeded its lifetime.')
        return DownloadGrant(prefix, expires, token, exact_name)

    def assert_exact_file(self, name):
        # Native B2 has prefix grants, not exact-file grants. Check every current
        # matching object, including non-catalog files. Never cache this check.
        listing = self.api.session.list_file_names(self.bucket_id, prefix=name, max_file_count=2)
        if ([item['fileName'] for item in listing['files']] != [name]
                or listing.get('nextFileName') is not None):
            raise MediaAccessError('MP4 filename prefix is missing or ambiguous.')

    def media_url(self, bucket, name, grant):
        if (not name.startswith(grant.prefix) or self.clock() >= grant.expires_at
                or (grant.exact_name is not None and name != grant.exact_name)):
            raise MediaAccessError('Object is outside the active movie grant.')
        # Validate components before the SDK constructs a download-by-name URL.
        if any(p in ('', '.', '..') for p in name.split('/')) or '\\' in name:
            raise MediaAccessError('Unsafe object name.')
        return bucket.get_download_url(name) + '?' + urlencode({'Authorization': grant.token})
