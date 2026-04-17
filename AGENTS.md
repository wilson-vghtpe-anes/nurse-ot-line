# Repository Guidelines

## Project Structure & Module Organization
`main.py` contains the FastAPI application, API routes, LINE webhook handling, and Supabase-facing business logic. Keep related helpers near the route group they support unless the file becomes large enough to justify extraction.

`docs/` holds static HTML pages and shared browser-side JavaScript:
- `docs/index.html`, `docs/admin.html`, `docs/manager.html`, `docs/nurse.html`
- `docs/share.js`

Deployment files live at the repo root: `Dockerfile`, `render.yaml`, `requirements.txt`, and `README.md`.

## Build, Test, and Development Commands
- `pip install -r requirements.txt`: install runtime and local development dependencies.
- `uvicorn main:app --host 0.0.0.0 --port 8000`: run the app locally.
- `docker build -t nurse-ot-line .`: build the production image defined in `Dockerfile`.
- `docker run -p 10000:10000 --env-file .env nurse-ot-line`: smoke-test the container locally.

Use `GET /health` to verify the service is up before testing webhook or admin flows.

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indentation and clear, small helper functions. Prefer `snake_case` for variables, functions, and internal helpers; use uppercase for environment variables such as `SUPABASE_URL`.

For FastAPI routes, keep path names resource-oriented and consistent with the existing style, for example `/api/records/me` and `/api/records/pending`. Avoid adding unrelated logic to route handlers when a helper function will keep flow clearer.

## Testing Guidelines
There is currently no `tests/` directory. Add new tests under `tests/` using `pytest`, with filenames like `test_health.py` or `test_overtime_api.py`.

At minimum, cover:
- `/health`
- key API permission paths
- webhook request handling

Run tests with `pytest` once test files are added. Prefer focused API tests over broad manual-only verification.

## Commit & Pull Request Guidelines
This workspace does not include Git history, so use short imperative commit messages such as `Add monthly summary validation` or `Fix webhook signature check`.

For pull requests, include:
- a brief problem/solution summary
- any new environment variables or config changes
- screenshots for `docs/` UI changes
- manual verification notes for API or webhook behavior

## Security & Configuration Tips
Do not hardcode secrets. Keep `LINE_CHANNEL_ACCESS_TOKEN`, `SUPABASE_URL`, and `SUPABASE_KEY` in environment variables or `.env`, and never commit real values.
