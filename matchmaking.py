import json
import time
import uuid
from redis.asyncio import Redis

QUEUE_KEY = "standknife:mm:solo"
LOCK_KEY = "standknife:mm:lock"
MATCH_SIZE = 10
INITIAL_RANGE = 50
RANGE_STEP = 50
MAX_RANGE = 300


async def add_to_queue(redis: Redis, user_id: int, elo: int, region: str = "EU"):
    player = {
        "user_id": user_id,
        "elo": elo,
        "region": region,
        "joined_at": time.time(),
    }
    await redis.hset(QUEUE_KEY, str(user_id), json.dumps(player))
    return player


async def remove_from_queue(redis: Redis, user_id: int):
    await redis.hdel(QUEUE_KEY, str(user_id))


async def get_queue(redis: Redis):
    raw = await redis.hgetall(QUEUE_KEY)
    result = []
    for value in raw.values():
        try:
            result.append(json.loads(value))
        except (TypeError, json.JSONDecodeError):
            pass
    return sorted(result, key=lambda x: x["joined_at"])


def elo_range_for_wait(joined_at: float) -> int:
    waited = max(0, time.time() - joined_at)
    return min(MAX_RANGE, INITIAL_RANGE + int(waited // 15) * RANGE_STEP)


def build_match(players: list[dict]) -> dict:
    players = sorted(players, key=lambda x: x["elo"], reverse=True)
    team_a = players[::2]
    team_b = players[1::2]
    return {
        "match_id": str(uuid.uuid4()),
        "team_a": team_a,
        "team_b": team_b,
        "status": "WAITING",
    }


async def try_create_match(redis: Redis):
    lock = redis.lock(LOCK_KEY, timeout=5, blocking_timeout=1)
    if not await lock.acquire():
        return None

    try:
        players = await get_queue(redis)
        if len(players) < MATCH_SIZE:
            return None

        for anchor in players:
            allowed = elo_range_for_wait(anchor["joined_at"])
            candidates = [
                p for p in players
                if p["user_id"] != anchor["user_id"]
                and p["region"] == anchor["region"]
                and abs(p["elo"] - anchor["elo"]) <= allowed
            ]
            candidates.sort(key=lambda p: (abs(p["elo"] - anchor["elo"]), p["joined_at"]))

            if len(candidates) < MATCH_SIZE - 1:
                continue

            selected = [anchor, *candidates[:MATCH_SIZE - 1]]
            ids = [p["user_id"] for p in selected]

            for user_id in ids:
                await remove_from_queue(redis, user_id)

            return build_match(selected)

        return None
    finally:
        try:
            await lock.release()
        except Exception:
            pass
