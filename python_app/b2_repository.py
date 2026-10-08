"""Read-only B2 catalog and bounded playlist downloads."""
from io import BytesIO
import threading
import time

from b2_media import B2Media, MediaAccessError, movie_prefix
from b2_policy import validate_scope


class B2Repository:
    def __init__(self, api, bucket_id, clock=time.time, discovery_prefix=''):
        self.api, self.bucket_id, self.clock = api, bucket_id, clock
        self.discovery_prefix = discovery_prefix
        self._catalog = None
        self._catalog_at = 0
        self._lock = threading.Lock()
        self.bucket = self.private_bucket()

    def private_bucket(self):
        validate_scope(self.api.account_info.get_allowed(), self.bucket_id)
        buckets = self.api.list_buckets(bucket_id=self.bucket_id, use_cache=False)
        if len(buckets) != 1 or buckets[0].id_ != self.bucket_id or buckets[0].type_ != 'allPrivate':
            raise MediaAccessError('Private bucket could not be verified.')
        return buckets[0]

    def catalog(self):
        with self._lock:
            if self._catalog is not None and self.clock() - self._catalog_at < 300:
                return self._catalog
            self.bucket = self.private_bucket()
            names = []
            for item, _ in self.bucket.ls(self.discovery_prefix, recursive=True, latest_only=True):
                name = item.file_name
                if name.startswith('_migration-test/') and not self.discovery_prefix:
                    continue
                if name.endswith('.hls/output.m3u8'):
                    movie_prefix(name)
                    names.append(name)
            self._catalog = tuple(sorted(names))
            self._catalog_at = self.clock()
            return self._catalog

    def grant(self, entry, parent_expires_at):
        media = B2Media(self.api, self.bucket_id, self.catalog(), self.clock)
        return media, media.grant(entry, parent_expires_at)

    def playlist(self, name, prefix):
        if (not name.startswith(prefix) or not name.endswith('.m3u8')
                or any(p in ('', '.', '..') for p in name.split('/'))):
            raise MediaAccessError('Invalid playlist scope.')
        # B2's SDK rejects ranges extending past EOF. Inspect metadata first and
        # request only a bounded range, even if an object is replaced afterward.
        info = self.bucket.get_file_info_by_name(name)
        if not 0 < info.size <= 1024 * 1024:
            raise MediaAccessError('Playlist exceeds size limit or is empty.')
        download = self.bucket.download_file_by_name(name, range_=(0, info.size - 1))
        data = BytesIO()
        download.save(data)
        if len(data.getvalue()) > 1024 * 1024:
            raise MediaAccessError('Playlist exceeds size limit.')
        return data.getvalue().decode('utf-8-sig')
