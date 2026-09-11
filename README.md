# STANDKNIFE — GitHub Ready

Telegram + Mini App competitive platform for StandKnife.

## 1. GitHub

Upload the contents of this folder to a GitHub repository.

Do NOT upload a real `.env` or a real Telegram bot token.

## 2. Environment

Create `.env` from `.env.example`:

```env
BOT_TOKEN=YOUR_REAL_BOT_TOKEN
DATABASE_URL=postgresql+asyncpg://standknife:password@postgres:5432/standknife
REDIS_URL=redis://redis:6379/0
JWT_SECRET=change_this_to_a_long_random_secret
JWT_EXPIRE_MINUTES=10080
WEBAPP_URL=https://geminialex12-hue/Panel
ADMIN_IDS=8297446667
INITIAL_ELO=1000
MATCH_SIZE=10
INITIAL_ELO_RANGE=50
MAX_ELO_RANGE=300
POSTGRES_PASSWORD=password
```

For GitHub/hosting, add these as repository/deployment secrets instead of committing them.

## 3. Run with Docker

```bash
docker compose up -d --build
```

Services:

- Frontend: port `3000`
- Backend: port `8000`
- PostgreSQL: internal Docker network
- Redis: internal Docker network
- Telegram bot: polling mode

## 4. Telegram Mini App

`WEBAPP_URL` must be a real HTTPS URL reachable by Telegram.

The value supplied in the current configuration is:

```text
https://geminialex12-hue/Panel
```

Make sure this is a valid deployed HTTPS address before production.

## 5. Security

Never commit:

- BOT_TOKEN
- JWT_SECRET
- PostgreSQL passwords
- private API keys

The previously supplied BOT_TOKEN was included in a chat message. For safety, rotate/revoke that bot token in BotFather and use the new token only as a deployment secret.

## 6. Important MVP behavior

StandKnife does not get fake match results from the client. Until an official StandKnife game API/webhook is available, match results use player confirmation.

The backend validates Telegram Mini App `initData` server-side.
