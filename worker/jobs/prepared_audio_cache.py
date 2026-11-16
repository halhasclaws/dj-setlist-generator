"""Print the GitHub Actions cache key for a set run's prepared audio.

The key pins the set run and the durable prepared-audio fingerprint, so a
continuation only ever restores the exact audio its first run recognized.
Public runs only; prints an empty key otherwise (no cache use).
"""
from __future__ import annotations

import os

from psycopg import connect
from psycopg.rows import dict_row


def cache_key(set_run_id: str) -> str:
    with connect(os.environ["DATABASE_URL_DIRECT"], autocommit=True, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select publication_visibility,
                   source_metadata->'shared_recognition'->>'audio_sha256' as audio_sha256
            from ops.set_runs where id = %s
            """,
            (set_run_id,),
        )
        row = cur.fetchone()
    if not row or row["publication_visibility"] != "public" or not row["audio_sha256"]:
        return ""
    return f"prepared-audio-v1-{set_run_id}-{row['audio_sha256']}"


if __name__ == "__main__":
    print(f"key={cache_key(os.environ['SET_RUN_ID'])}")
