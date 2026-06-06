# Pirple — Backend API

A privacy-first REST API for tracking alcohol consumption and generating personalised analytics. Built with **FastAPI** and **PostgreSQL**, deployed on **Render**.

---

## Overview

Pirple's backend powers the [mobile frontend](https://github.com/jessemutua/alc_data_fe). It handles user authentication, drink session logging, sober day tracking, calendar views, and analytics aggregation — all scoped per user via JWT auth.

---

## Features

- **Auth** — Email/password registration and login with Argon2 password hashing and JWT bearer tokens (7-day expiry by default)
- **Drink Session Logging** — Create, update, and delete drinking sessions per day. Each session records a time window, drink types (beer/wine/spirits/other), and quantities. Supports both single and batch creation
- **Sober Day Logging** — Mark (and unmark) sober days explicitly. Idempotent upsert — safe to call multiple times
- **Calendar View** — Fetch a month's worth of logged dates with per-day totals (quantity, session count, drinking vs sober)
- **Analytics** — Aggregated stats over a configurable day window (default 30 days): daily trend, 7-day rolling average, drink type breakdown, time-of-day patterns, weekend vs weekday comparison, and summary stats
- **Admin** — Token-protected endpoint to trigger a database metrics refresh

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.128 |
| Server | Uvicorn |
| ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL (psycopg2) |
| Auth | JWT via `python-jose` + Argon2 via `passlib` |
| Validation | Pydantic v2 |
| Deployment | Render (free tier) |

---

## Project Structure

```
pirple_alc_data/
├── main.py                        # App entry point — routers, CORS, startup
│
├── core/
│   ├── config.py                  # Loads env vars (DATABASE_URL, JWT_SECRET, etc.)
│   ├── database.py                # SQLAlchemy engine, session, Base, init_db()
│   ├── deps.py                    # Shared FastAPI dependencies
│   └── security.py                # Password hashing, JWT creation & verification
│
├── auth/
│   ├── models.py                  # User table (id, email, password_hash, created_at)
│   ├── schemas.py                 # AuthPayload, AuthResponse (Pydantic)
│   └── routes.py                  # POST /auth/register, POST /auth/login
│
├── drinks/
│   ├── session_models.py          # DrinkSession + DrinkSessionItem tables
│   ├── session_schemas.py         # Create/Update/Batch session payloads (Pydantic)
│   ├── session_routes.py          # CRUD for /sessions + /sessions/day
│   ├── calendar_routes.py         # GET /calendar/month
│   ├── sober_models.py            # SoberDay table
│   ├── sober_schemas.py           # Sober day payloads (Pydantic)
│   └── sober_routes.py            # POST /sober-days, DELETE /sober-days/{date}
│
├── analytics/
│   ├── service.py                 # Pure analytics computation (build_user_analytics)
│   ├── routes.py                  # GET /analytics
│   └── refresh_routes.py          # POST /admin/refresh-metrics
│
├── cors.py                        # CORS helpers
├── requirements.txt               # Python dependencies
└── render.yaml                    # Render deployment config
```

---

## API Reference

All endpoints except `/auth/*` require an `Authorization: Bearer <token>` header.

### Auth

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/register` | Create account. Returns `access_token` + user object |
| `POST` | `/auth/login` | Sign in. Returns `access_token` + user object |

**Request body (both):**
```json
{ "email": "user@example.com", "password": "min8chars" }
```

**Response:**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": { "id": "uuid", "email": "user@example.com", "created_at": "..." }
}
```

---

### Drink Sessions

| Method | Path | Description |
|---|---|---|
| `POST` | `/sessions` | Log a single drink session |
| `POST` | `/sessions/batch` | Log multiple sessions at once |
| `PUT` | `/sessions/{session_id}` | Update an existing session |
| `DELETE` | `/sessions/{session_id}` | Delete a session |
| `GET` | `/sessions/day?date=YYYY-MM-DD` | Fetch all sessions + day totals for a date |

**Create session body:**
```json
{
  "log_date": "2026-06-01",
  "time_window": "evening",
  "items": [
    { "drink_type": "beer", "quantity": 2 },
    { "drink_type": "wine", "quantity": 1 }
  ],
  "notes": "friend's birthday"
}
```

Valid `time_window` values: `morning`, `afternoon`, `evening`, `night`, `late_night`

Valid `drink_type` values: `beer`, `wine`, `spirits`, `other`

---

### Sober Days

| Method | Path | Description |
|---|---|---|
| `POST` | `/sober-days` | Mark a date as sober (idempotent) |
| `DELETE` | `/sober-days/{date}` | Unmark a sober day (idempotent) |

**Request body (POST):**
```json
{ "date": "2026-06-01" }
```

Future dates are rejected with a 400 error.

---

### Calendar

| Method | Path | Description |
|---|---|---|
| `GET` | `/calendar/month?month=YYYY-MM` | Fetch all logged dates for a month |

**Response shape:**
```json
{
  "2026-06-01": { "hasDrinking": true,  "totalQuantity": 3, "sessionCount": 2 },
  "2026-06-03": { "hasDrinking": false, "totalQuantity": 0, "sessionCount": 0 }
}
```

Dates absent from the map are unlogged. Sober days appear with `hasDrinking: false`.

---

### Analytics

| Method | Path | Description |
|---|---|---|
| `GET` | `/analytics?days=30` | Aggregated analytics for the last N days |

**Response shape:**
```json
{
  "meta": { "requestedDays": 30, "availableDays": 30, "from": "...", "to": "..." },
  "summary": {
    "daysTracked": 30,
    "drinkingDays": 12,
    "soberDays": 8,
    "sessionCount": 18,
    "totalQuantity": 47,
    "avgQuantityPerDay": 1.57,
    "avgQuantityPerDrinkingDay": 3.92,
    "maxDailyQuantity": 6
  },
  "trend": {
    "daily": [{ "date": "2026-05-08", "hasDrinking": true, "totalQuantity": 3, "sessionCount": 1 }],
    "rollingAvg7dQuantity": [{ "date": "2026-05-08", "value": 1.43 }]
  },
  "timePattern": { "evening": 10, "night": 5, "afternoon": 3, "morning": 0, "late_night": 0 },
  "drinkTypes": { "beer": 22, "wine": 14, "spirits": 8, "other": 3 },
  "weekendVsWeekday": {
    "weekend": { "drinkingDays": 6, "sessionCount": 9, "totalQuantity": 24 },
    "weekday": { "drinkingDays": 6, "sessionCount": 9, "totalQuantity": 23 }
  }
}
```

---

### Admin

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/refresh-metrics` | Trigger DB metrics refresh (token-protected) |

Requires `Authorization: Bearer <METRICS_TOKEN>` where `METRICS_TOKEN` is the env var.

---

## Getting Started (Local)

### Prerequisites

- Python 3.11+
- PostgreSQL running locally (or a connection string to a remote DB)

### Setup

```bash
git clone https://github.com/jessemutua/pirple_alc_data.git
cd pirple_alc_data
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/pirple
JWT_SECRET=your-secret-key-here
JWT_EXPIRE_HOURS=168
METRICS_TOKEN=your-admin-token
```

> If your `DATABASE_URL` starts with `postgres://` (e.g. from Render or Heroku), the app automatically rewrites it to `postgresql+psycopg2://`.

### Run

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`.

Interactive docs: `http://localhost:8000/docs`

Tables are created automatically on startup via `init_db()`.

---

## Deployment (Render)

The `render.yaml` in the repo configures Render deployment automatically.

```yaml
services:
  - type: web
    name: pirple-backend
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
```

**Steps to deploy:**

1. Push the repo to GitHub
2. Go to [render.com](https://render.com) → New → Blueprint
3. Connect the repo — Render will pick up `render.yaml` and provision both the web service and a PostgreSQL database
4. Add the following environment variables in the Render dashboard:
   - `JWT_SECRET` — a long random string
   - `METRICS_TOKEN` — token for the admin endpoint
   - `DATABASE_URL` is set automatically by Render when the database is linked

---

## Data Models

### `users`
| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Primary key |
| `email` | String | Unique, indexed |
| `password_hash` | String | Argon2 hash |
| `created_at` | DateTime (UTC) | Server default |

### `drink_sessions`
| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Primary key |
| `user_id` | String | References `users.id` |
| `log_date` | Date | The date being logged |
| `occurred_at` | DateTime (UTC) | Derived from `log_date` + `time_window` if not provided explicitly |
| `time_window` | String | `morning/afternoon/evening/night/late_night` |
| `source` | String | `manual` or `scan` |
| `notes` | String | Optional |

### `drink_session_items`
| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Primary key |
| `session_id` | String | FK → `drink_sessions.id` (cascade delete) |
| `drink_type` | String | `beer/wine/spirits/other` |
| `quantity` | Integer | ≥ 0 |
| `auth_status` | String | `unknown/verified/suspicious` |

### `sober_days`
| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Primary key |
| `user_id` | String | References `users.id` |
| `log_date` | Date | Unique per user |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `JWT_SECRET` | Yes | `dev-secret` | Secret for signing JWTs — **change in production** |
| `JWT_EXPIRE_HOURS` | No | `168` (7 days) | JWT lifetime in hours |
| `METRICS_TOKEN` | No | `""` | Bearer token for `/admin/refresh-metrics` |

---

## License

Private — all rights reserved.
