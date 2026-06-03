from redis.asyncio import Redis

from app.config import get_settings


def _make_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


redis_client: Redis = _make_redis_client()


async def get_redis() -> Redis:
    return redis_client
