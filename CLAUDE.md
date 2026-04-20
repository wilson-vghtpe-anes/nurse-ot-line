# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (default port 8000)
uvicorn main:app --host 0.0.0.0 --port 8000

# Build Docker image
docker build -t nurse-ot-line .

# Run container locally
docker run -p 10000:10000 --env-file .env nurse-ot-line

# Run tests (add files under tests/ first)
pytest
```

Verify the service is healthy via `GET /health` after startup.

## Environment Variables

Required in `.env`:
```
LINE_CHANNEL_ACCESS_TOKEN=
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=
```

## Architecture

This is a single-file FastAPI app (`main.py`) serving as a LINE bot webhook + REST API backend for a hospital nurse overtime tracking system.

**External services (no ORM, raw HTTP):**
- **Supabase** — PostgreSQL accessed via Supabase REST API using `requests`. `SUPABASE_HEADERS` is the shared auth header dict used for all DB calls.
- **LINE Messaging API** — `reply_message()` for webhook replies, `push_message()` for proactive pushes.

**Two Supabase tables:**
- `nurses` — columns: `id, name, role, line_user_id, bound_at`. Roles: `nurse | manager | admin | pending`.
- `overtime_records` — columns: `id, user_id, work_date, shift_type, other_shift_text, overtime_minutes, record_type, status`. Statuses: `審核中 | 已核准 | 已拒絕 | 已取消`. Negative `overtime_minutes` = early leave (`record_type="leave_early"`).

**Two user interfaces:**
1. **LINE bot** (`POST /webhook`) — text command parsing. Commands include: `綁定`, `加班`, `早走`, `取消`, `我的記錄`, `全員查詢`, `月份統計`, `核准`, `拒絕`, `待審清單`, `成員清單`, `設定角色`, `移除角色`, `待審名單`, `刪除護理師`.
2. **LIFF web UI** (`docs/`) — static HTML pages served by FastAPI at `/index.html`, `/nurse.html`, `/manager.html`, `/admin.html`. These call the REST API using `X-Line-User-Id` header for auth (from `liff.getProfile()`).

**REST API authentication** (`get_current_user`): reads `X-Line-User-Id` header, looks up nurse record in Supabase, rejects `pending` role. `require_manager` allows `manager` or `admin`; `require_admin` requires `admin` only.

**Key REST endpoints:**
- `GET /api/me` — current user info
- `POST /api/bind` — bind LINE user to name
- `GET /api/records/me` — own records (supports `?month=YYYY-MM`, `?start=`, `?end=`)
- `POST /api/overtime` — submit overtime/leave-early
- `POST /api/overtime/{id}/cancel` — cancel own pending record
- `GET /api/records/pending` — pending records for manager review
- `GET /api/records/all` — all records with per-person totals (manager)
- `GET /api/records/monthly-summary` — yearly monthly breakdown (manager)
- `POST /api/records/{id}/review` — approve/reject (manager)
- `GET /api/members` — member list (admin)
- `POST /api/members/role` — set role (admin)

**Deployment:** Docker on Render. Port is read from `$PORT` env var (default `10000`). `render.yaml` configures the service with health check at `/health`.

## Code Style

- PEP 8, 4-space indentation, `snake_case` for functions/variables.
- Keep all logic in `main.py` unless the file grows large enough to justify extraction.
- Route handlers call named helper functions; don't embed Supabase URL construction inline in handlers.
- Overtime duration is always stored in **minutes** as integers. Use `format_minutes()` for display.
- The `parse_overtime_command()` function is reused for both `加班` and `早走` commands (the latter prepends `加班` to normalize input).

## Testing

No tests exist yet. Add under `tests/` using `pytest`. Minimum coverage: `/health`, API permission paths, webhook command parsing.
