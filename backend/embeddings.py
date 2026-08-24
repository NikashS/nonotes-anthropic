from __future__ import annotations

import json
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

# This is Supabase's publishable, browser-safe anon key, not a service-role secret.
# Environment variables can override both values for forks and local stacks.
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://shhoexwxkopxcarjllzs.supabase.co").rstrip("/")
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNoaG9leHd4a29weGNhcmpsbHpzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1MDg2NzUsImV4cCI6MjEwMzA4NDY3NX0.lbpwiZ7VOugnhTc-dcq5uiq9ZVs58pdBB6FdnqNqcl4",
)


async def generate_embedding(text: str) -> list[float] | None:
    """Generate a normalized 384d gte-small embedding in Supabase Edge Runtime."""
    value = " ".join(text.split())[:16_000]
    if not value or not SUPABASE_ANON_KEY:
        return None
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "content-type": "application/json",
    }
    started = time.perf_counter()
    succeeded = False
    try:
        timeout = httpx.Timeout(7, connect=3, write=3, pool=3)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{SUPABASE_URL}/functions/v1/embed",
                headers=headers,
                json={"input": value},
            )
            response.raise_for_status()
        embedding = response.json().get("embedding")
        if isinstance(embedding, list) and len(embedding) == 384:
            succeeded = True
            return [float(item) for item in embedding]
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        logger.warning("Semantic embedding unavailable: %s", type(exc).__name__)
    finally:
        logger.info(json.dumps({
            "level": "info", "message": "latency.stage", "stage": "embedding.remote",
            "duration_ms": round((time.perf_counter() - started) * 1000), "available": succeeded,
        }))
    return None
