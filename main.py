import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from database import Base, engine, get_db, settings
from models import User, Profile, Party, PartyMember, Match, MatchPlayer, EloHistory
from elo import get_rank, calculate_elo
from matchmaking import add_to_queue, remove_from_queue, get_queue, try_create_match


app = FastAPI(title="STANDKNIFE API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

redis = Redis.from_url(settings.redis_url, decode_responses=False)


class TelegramAuth(BaseModel):
    init_data: str = Field(min_length=1, max_length=10000)


class RegistrationData(BaseModel):
    nickname: str = Field(min_length=2, max_length=32)
    game_id: str = Field(min_length=1, max_length=64)


class QueueData(BaseModel):
    region: str = Field(default="EU", min_length=2, max_length=8)


class PartyCreate(BaseModel):
    max_size: int = Field(default=5, ge=2, le=5)


class PartyJoin(BaseModel):
    party_id: int = Field(gt=0)


class ResultData(BaseModel):
    winner_team: str = Field(pattern="^[AB]$")
    team_a_score: int = Field(ge=0, le=99)
    team_b_score: int = Field(ge=0, le=99)


def validate_telegram_init_data(init_data: str) -> dict:
    if not settings.bot_token:
        raise HTTPException(500, "BOT_TOKEN is not configured")

    parsed = dict(parse_qsl(init_data))
    received_hash = parsed.pop("hash", None)

    if not received_hash:
        raise HTTPException(401, "Telegram hash missing")

    auth_date = parsed.get("auth_date")
    if not auth_date:
        raise HTTPException(401, "Telegram auth_date missing")

    try:
        if time.time() - int(auth_date) > 86400:
            raise HTTPException(401, "Telegram initData expired")
    except ValueError:
        raise HTTPException(401, "Invalid auth_date")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        raise HTTPException(401, "Invalid Telegram signature")

    try:
        user = json.loads(parsed["user"])
    except (KeyError, json.JSONDecodeError):
        raise HTTPException(401, "Invalid Telegram user")

    if "id" not in user:
        raise HTTPException(401, "Telegram user ID missing")

    return user


async def current_user(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if not authorization or not authorization.startswith("Telegram "):
        raise HTTPException(401, "Telegram authorization required")

    tg_user = validate_telegram_init_data(authorization[9:])

    result = await db.execute(
        select(User)
        .options(selectinload(User.profile))
        .where(User.telegram_id == tg_user["id"])
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "User is not registered")

    if user.is_banned:
        raise HTTPException(403, "User is banned")

    return user


@app.on_event("startup")
async def startup():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@app.on_event("shutdown")
async def shutdown():
    await redis.close()
    await engine.dispose()


@app.get("/")
async def root():
    return {"name": "STANDKNIFE API", "status": "online", "version": "1.0.0"}


@app.get("/health")
async def health():
    await redis.ping()
    return {"status": "ok", "database": "configured", "redis": "ok"}


@app.post("/api/auth/telegram")
async def telegram_auth(data: TelegramAuth, db: AsyncSession = Depends(get_db)):
    tg_user = validate_telegram_init_data(data.init_data)

    result = await db.execute(
        select(User)
        .options(selectinload(User.profile))
        .where(User.telegram_id == tg_user["id"])
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=tg_user["id"],
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name"),
        )
        db.add(user)
        await db.commit()
        return {"registered": False}

    user.username = tg_user.get("username", user.username)
    user.first_name = tg_user.get("first_name", user.first_name)
    await db.commit()

    return {"registered": user.profile is not None}


@app.post("/api/auth/register")
async def register(data: RegistrationData, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if user.profile:
        raise HTTPException(409, "Profile already exists")

    duplicate = await db.execute(
        select(Profile).where(Profile.game_id == data.game_id)
    )
    if duplicate.scalar_one_or_none():
        raise HTTPException(409, "This game ID is already registered")

    user.accepted_terms = True
    profile = Profile(
        user_id=user.id,
        game_nickname=data.nickname.strip(),
        game_id=data.game_id.strip(),
        elo=settings.initial_elo,
    )
    db.add(profile)
    await db.commit()

    return {"success": True, "nickname": profile.game_nickname, "elo": profile.elo}


@app.get("/api/profile")
async def profile(user: User = Depends(current_user)):
    if not user.profile:
        raise HTTPException(404, "Profile not found")

    p = user.profile
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "nickname": p.game_nickname,
        "game_id": p.game_id,
        "elo": p.elo,
        "rank": get_rank(p.elo),
        "wins": p.wins,
        "losses": p.losses,
        "kills": p.kills,
        "deaths": p.deaths,
        "premium": p.premium,
    }


@app.get("/api/stats")
async def stats(user: User = Depends(current_user)):
    if not user.profile:
        raise HTTPException(404, "Profile not found")

    p = user.profile
    games = p.wins + p.losses
    winrate = round(p.wins / games * 100, 1) if games else 0
    kd = round(p.kills / p.deaths, 2) if p.deaths else float(p.kills)

    return {
        "games": games,
        "wins": p.wins,
        "losses": p.losses,
        "winrate": winrate,
        "kills": p.kills,
        "deaths": p.deaths,
        "kd": kd,
        "elo": p.elo,
        "rank": get_rank(p.elo),
    }


@app.post("/api/matchmaking/join")
async def matchmaking_join(data: QueueData, user: User = Depends(current_user)):
    if not user.profile:
        raise HTTPException(400, "Complete registration first")

    await add_to_queue(redis, user.id, user.profile.elo, data.region.upper())
    match = await try_create_match(redis)

    if match:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            db_match = Match(mode="5V5", status="READY")
            db.add(db_match)
            await db.flush()

            for team, key in (("A", "team_a"), ("B", "team_b")):
                for player in match[key]:
                    db.add(MatchPlayer(
                        match_id=db_match.id,
                        user_id=player["user_id"],
                        team=team,
                    ))

            await db.commit()
            return {"status": "match_found", "match_id": db_match.id}

    return {"status": "searching"}


@app.post("/api/matchmaking/leave")
async def matchmaking_leave(user: User = Depends(current_user)):
    await remove_from_queue(redis, user.id)
    return {"status": "left_queue"}


@app.get("/api/matchmaking/status")
async def matchmaking_status(user: User = Depends(current_user)):
    queue = await get_queue(redis)
    item = next((p for p in queue if p["user_id"] == user.id), None)

    if item:
        return {
            "status": "searching",
            "position": queue.index(item) + 1,
            "queue_size": len(queue),
        }

    result = await redis.get(f"standknife:user_match:{user.id}")
    return {"status": "idle", "match_id": int(result) if result else None}


@app.post("/api/party/create")
async def party_create(data: PartyCreate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(PartyMember)
        .where(PartyMember.user_id == user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Already in a party")

    party = Party(leader_id=user.id, max_size=data.max_size)
    db.add(party)
    await db.flush()
    db.add(PartyMember(party_id=party.id, user_id=user.id))
    await db.commit()

    return {"party_id": party.id, "leader_id": user.id, "max_size": party.max_size}


@app.post("/api/party/join")
async def party_join(data: PartyJoin, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(PartyMember).where(PartyMember.user_id == user.id))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Already in a party")

    result = await db.execute(
        select(Party)
        .options(selectinload(Party.members))
        .where(Party.id == data.party_id)
    )
    party = result.scalar_one_or_none()

    if not party:
        raise HTTPException(404, "Party not found")
    if len(party.members) >= party.max_size:
        raise HTTPException(409, "Party is full")

    db.add(PartyMember(party_id=party.id, user_id=user.id))
    await db.commit()

    return {"success": True, "party_id": party.id}


@app.post("/api/party/leave")
async def party_leave(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PartyMember).where(PartyMember.user_id == user.id)
    )
    member = result.scalar_one_or_none()

    if not member:
        return {"success": True}

    await db.delete(member)
    await db.commit()
    return {"success": True}


@app.get("/api/party")
async def party_get(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PartyMember)
        .options(selectinload(PartyMember.party).selectinload(Party.members))
        .where(PartyMember.user_id == user.id)
    )
    member = result.scalar_one_or_none()

    if not member:
        return {"party": None}

    return {
        "party": {
            "id": member.party.id,
            "leader_id": member.party.leader_id,
            "max_size": member.party.max_size,
            "members": [m.user_id for m in member.party.members],
        }
    }


@app.get("/api/players/search")
async def player_search(
    q: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    q = q.strip()
    if len(q) < 2:
        return {"players": []}

    result = await db.execute(
        select(Profile)
        .where(Profile.game_nickname.ilike(f"%{q}%"))
        .limit(20)
    )

    return {
        "players": [
            {
                "nickname": p.game_nickname,
                "game_id": p.game_id,
                "elo": p.elo,
                "rank": get_rank(p.elo),
            }
            for p in result.scalars()
        ]
    }


@app.get("/api/matches/{match_id}")
async def get_match(match_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.players))
        .where(Match.id == match_id)
    )
    match = result.scalar_one_or_none()

    if not match:
        raise HTTPException(404, "Match not found")

    if not any(p.user_id == user.id for p in match.players):
        raise HTTPException(403, "You are not in this match")

    return {
        "id": match.id,
        "mode": match.mode,
        "status": match.status,
        "result_status": match.result_status,
        "team_a": [p.user_id for p in match.players if p.team == "A"],
        "team_b": [p.user_id for p in match.players if p.team == "B"],
    }


@app.post("/api/matches/{match_id}/result")
async def submit_result(
    match_id: int,
    data: ResultData,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.players))
        .where(Match.id == match_id)
    )
    match = result.scalar_one_or_none()

    if not match:
        raise HTTPException(404, "Match not found")

    player = next((p for p in match.players if p.user_id == user.id), None)
    if not player:
        raise HTTPException(403, "You are not in this match")

    if match.status == "FINISHED":
        raise HTTPException(409, "Match already finished")

    player.result_confirmed = True
    match.team_a_score = data.team_a_score
    match.team_b_score = data.team_b_score
    match.winner_team = data.winner_team

    confirmations = sum(1 for p in match.players if p.result_confirmed)

    if confirmations >= 2:
        match.status = "FINISHED"
        match.result_status = "CONFIRMED"

        team_a = [p for p in match.players if p.team == "A"]
        team_b = [p for p in match.players if p.team == "B"]

        avg_a = round(
            sum((await db.get(Profile, p.user_id)).elo for p in team_a) / len(team_a)
        )
        avg_b = round(
            sum((await db.get(Profile, p.user_id)).elo for p in team_b) / len(team_b)
        )

        for mp in match.players:
            p = await db.get(Profile, mp.user_id)
            before = p.elo
            opponent = avg_b if mp.team == "A" else avg_a
            won = mp.team == data.winner_team
            change = calculate_elo(before, opponent, won)

            p.elo += change
            if won:
                p.wins += 1
            else:
                p.losses += 1

            mp.elo_before = before
            mp.elo_change = change
            mp.elo_after = p.elo

            db.add(EloHistory(
                user_id=p.user_id,
                match_id=match.id,
                before_elo=before,
                change=change,
                after_elo=p.elo,
            ))

    await db.commit()

    return {
        "status": match.status,
        "confirmations": confirmations,
        "required": 2,
    }



@app.post("/api/bot/register")
async def bot_register(
    data: dict,
    x_bot_token: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if not x_bot_token or not hmac.compare_digest(x_bot_token, settings.bot_token):
        raise HTTPException(403, "Invalid bot authorization")

    telegram_id = int(data["telegram_id"])

    result = await db.execute(
        select(User)
        .options(selectinload(User.profile))
        .where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=telegram_id,
            username=None,
            first_name=None,
            accepted_terms=True,
        )
        db.add(user)
        await db.flush()

    if user.profile:
        raise HTTPException(409, "Profile already exists")

    duplicate = await db.execute(
        select(Profile).where(Profile.game_id == str(data["game_id"]))
    )
    if duplicate.scalar_one_or_none():
        raise HTTPException(409, "This game ID is already registered")

    user.accepted_terms = True
    profile = Profile(
        user_id=user.id,
        game_nickname=str(data["nickname"]).strip(),
        game_id=str(data["game_id"]).strip(),
        elo=settings.initial_elo,
    )
    db.add(profile)
    await db.commit()

    return {"success": True, "user_id": user.id, "elo": profile.elo}


@app.post("/api/bot/user")
async def bot_user(
    data: dict,
    x_bot_token: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if not x_bot_token or not hmac.compare_digest(x_bot_token, settings.bot_token):
        raise HTTPException(403, "Invalid bot authorization")

    telegram_id = int(data["telegram_id"])

    result = await db.execute(
        select(User)
        .options(selectinload(User.profile))
        .where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=telegram_id,
            username=data.get("username"),
            first_name=data.get("first_name"),
        )
        db.add(user)
        await db.commit()
        return {"registered": False}

    return {
        "registered": user.profile is not None,
        "user_id": user.id,
    }
