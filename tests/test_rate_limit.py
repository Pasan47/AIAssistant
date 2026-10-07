import asyncio

from app.rate_limit import TokenBucketLimiter


def test_bucket_exhausts_then_refills_per_user():
    now = [0.0]
    limiter = TokenBucketLimiter(capacity=2, refill_per_sec=1.0, clock=lambda: now[0])

    async def scenario():
        assert (await limiter.try_consume("a"))[0] and (await limiter.try_consume("a"))[0]
        ok, retry = await limiter.try_consume("a")
        assert not ok and 0 < retry <= 1.0
        assert (await limiter.try_consume("b"))[0]       # other users unaffected
        now[0] += 1.0
        assert (await limiter.try_consume("a"))[0]       # refilled

    asyncio.run(scenario())
