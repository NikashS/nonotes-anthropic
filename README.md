# No Notes

No Notes is a persistent, spatial AI workspace. Ask from anywhere; the system retrieves the relevant work and streams a themed generative document into the right place—modifying or extending existing work in place.

## Local development

Requirements: Node 20+, pnpm, and Python 3.12+.

```bash
cp .env.example .env
python -m venv .venv
.venv/bin/pip install -e backend
pnpm --dir frontend install
.venv/bin/uvicorn backend.main:app --reload --port 8000
pnpm --dir frontend dev
```

The application works in a deterministic local mode without an API key. Add a fresh `ANTHROPIC_API_KEY` to `.env` to enable Claude-generated compositions.

## Deployment

The repository is configured as a Vercel Services project: Vite at `/` and FastAPI at `/api`. FastAPI compiles validated compositions into safe HTML fragments streamed over NDJSON. Production should use a Postgres `DATABASE_URL`; local development defaults to SQLite.
