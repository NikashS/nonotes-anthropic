"""Stable Vercel Python Function entrypoint for the FastAPI service."""

from fastapi import FastAPI

from backend.main import app as backend_app


app = FastAPI()
# Rewrites normally preserve the public /api prefix. The root mount also keeps
# the entrypoint compatible with runtimes that strip the function prefix.
app.mount("/api", backend_app)
app.mount("/", backend_app)
