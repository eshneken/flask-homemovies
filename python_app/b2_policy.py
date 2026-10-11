"""Fail-closed policy for native B2 playback credentials."""

REQUIRED = {"listBuckets", "listFiles", "readFiles", "shareFiles"}
READ_CAPABILITIES = REQUIRED | {
    "readBuckets", "readBucketEncryption", "readBucketRetentions",
    "readFileLegalHolds", "readFileRetentions", "readBucketReplications",
    "readBucketNotifications", "readBucketLogging", "readBucketLifecycleRules",
}


class UnsafeConfiguration(ValueError):
    pass


def validate_scope(allowed, bucket_id):
    """Fail closed on unrestricted, multi-bucket, write, or unknown permissions."""
    buckets = allowed.get("buckets")
    if not isinstance(buckets, list) or len(buckets) != 1:
        raise UnsafeConfiguration("Use a standard key restricted to exactly one bucket.")
    if not isinstance(buckets[0], dict) or buckets[0].get("id") != bucket_id:
        raise UnsafeConfiguration("Key scope does not match the configured bucket.")
    caps = allowed.get("capabilities")
    if not isinstance(caps, list) or any(not isinstance(c, str) for c in caps):
        raise UnsafeConfiguration("Unrecognized key capability response.")
    caps = set(caps)
    if not REQUIRED <= caps:
        raise UnsafeConfiguration("Key needs listBuckets, listFiles, readFiles and shareFiles.")
    if "listAllBucketNames" in caps:
        raise UnsafeConfiguration("Create a replacement key with Allow List All Bucket Names unchecked.")
    if not caps <= READ_CAPABILITIES:
        raise UnsafeConfiguration("Key includes unnecessary or unrecognized capabilities.")
    if allowed.get("namePrefix") not in (None, "") or "namePrefix" not in allowed:
        raise UnsafeConfiguration("Playback key must cover the catalog within its single bucket.")
