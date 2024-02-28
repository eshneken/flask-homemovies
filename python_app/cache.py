from redis import Redis

#
# Abstract base class for cache implementations
#
class CacheProvider:
    def __str(self, hostname):
        return "Cache provider: " + hostname

#
# Local cache provider using an in-memory dictionary
#
class LocalCacheProvider(CacheProvider):
    def __init__(self, hostname):
        self.authenticated = {}
        self.shared = {}

    def get_authenticated_dict(self):
        return self.authenticated
    
    def set_authenticated(self, session_id: str, value: bool):
        self.authenticated[session_id] = value

    def get_authenticated(self, session_id: str) -> bool:
        try:
            return self.authenticated[session_id]
        except: 
            return False
    
    def is_session_in_authenticated(self, session_id: str) -> bool:
        return session_id in self.authenticated
    
    def set_shared(self, auth_id: str, value: str):
        self.shared[auth_id] = value

    def get_shared(self, auth_code: str) -> str:
        try:
            return self.shared[auth_code]
        except:
            return False

#
# Cache provider leveraging OCI Redis Service
#
class RedisCacheProvider(CacheProvider):
    def __init__(self, hostname):
        self.redis = Redis(host=hostname, port=6379, ssl=True, ssl_cert_reqs="none", decode_responses=True)

    def get_authenticated_dict(self):
        cache_contents = {}
        keys = self.redis.keys("auth:*")
        for key in keys:
            value = self.redis.get(key)
            cache_contents[key] = value
        return cache_contents
    
    # record the auth session id for 15 minutes
    def set_authenticated(self, session_id: str, value: bool):
        self.redis.setex(f"auth:{session_id}", 60*15, str(value))

    def get_authenticated(self, session_id: str) -> bool:
        result = self.redis.get(f"auth:{session_id}").lower()
        if result == "true":
            return True
        else:
            return False
    
    def is_session_in_authenticated(self, session_id: str) -> bool:
        if self.redis.exists(f"auth:{session_id}"):
            return True
        else:
            return False

    # record the share auth code for 48 hours.  value is the name of the movie 
    def set_shared(self, auth_id: str, value: str):
        self.redis.setex(f"shared:{auth_id}", 60*60*48, value)

    # return the name of the movie matching the authcode
    def get_shared(self, auth_code: str) -> str:
        if self.redis.exists(f"shared:{auth_code}") == False:
            return None
        return self.redis.get(f"shared:{auth_code}")


#
# Factory to return appropriate cache based on input type
#
class CacheProviderFactory:
    @staticmethod
    def get_cache_provider(provider_type, hostname):
        if provider_type == 'local':
            return LocalCacheProvider(hostname)
        elif provider_type == 'cloud':
            return RedisCacheProvider(hostname)
        else:
            raise ValueError("Invalid cache provider type: must be local or cloud")