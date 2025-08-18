# core/redis_utils.py

from packaging.version import parse

def hset_compat(redis_client, key, mapping):
    """
    Provides compatibility for the HSET command between older and newer
    versions of Redis.

    - For Redis >= 4.0.0, it uses HSET with multiple field/value pairs.
    - For Redis < 4.0.0, it falls back to the deprecated HMSET command.
    """
    # Get the server's Redis version
    redis_version = redis_client.info().get('redis_version', '0.0.0')

    # Use the modern HSET command if the version is 4.0.0 or newer
    if parse(redis_version) >= parse("4.0.0"):
        redis_client.hset(key, mapping=mapping)
    else:
        # Fall back to the older HMSET for compatibility
        redis_client.hmset(key, mapping)
