from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "submissions.db"


def init_submissions_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submitted_at TEXT NOT NULL,
                contributor_name TEXT,
                contributor_id TEXT,
                selected_area TEXT NOT NULL,
                nearest_area TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                risk_label TEXT NOT NULL,
                risk_score REAL NOT NULL,
                next_2h_probability REAL NOT NULL,
                blockage_score REAL NOT NULL,
                rainfall_used_mm_hr REAL NOT NULL,
                rainfall_source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Reported',
                image_name TEXT,
                image_bytes BLOB
            )
            """
        )

        # Lightweight migration for existing databases created before status lifecycle.
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(submissions)").fetchall()
        }
        if "status" not in existing_cols:
            conn.execute(
                "ALTER TABLE submissions ADD COLUMN status TEXT NOT NULL DEFAULT 'Reported'"
            )
        if "contributor_name" not in existing_cols:
            conn.execute("ALTER TABLE submissions ADD COLUMN contributor_name TEXT")
        if "contributor_id" not in existing_cols:
            conn.execute("ALTER TABLE submissions ADD COLUMN contributor_id TEXT")
        if "image_name" not in existing_cols:
            conn.execute("ALTER TABLE submissions ADD COLUMN image_name TEXT")
        if "image_bytes" not in existing_cols:
            conn.execute("ALTER TABLE submissions ADD COLUMN image_bytes BLOB")

        conn.commit()


def insert_submission(record: dict) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT INTO submissions (
                submitted_at,
                contributor_name,
                contributor_id,
                selected_area,
                nearest_area,
                lat,
                lon,
                risk_label,
                risk_score,
                next_2h_probability,
                blockage_score,
                rainfall_used_mm_hr,
                rainfall_source,
                status,
                image_name,
                image_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["submitted_at"],
                record.get("contributor_name"),
                record.get("contributor_id"),
                record["selected_area"],
                record["nearest_area"],
                record["lat"],
                record["lon"],
                record["risk_label"],
                record["risk_score"],
                record["next_2h_probability"],
                record["blockage_score"],
                record["rainfall_used_mm_hr"],
                record["rainfall_source"],
                record.get("status", "Reported"),
                record.get("image_name"),
                record.get("image_bytes"),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def fetch_submissions() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                id,
                submitted_at,
                contributor_name,
                contributor_id,
                selected_area,
                nearest_area,
                lat,
                lon,
                risk_label,
                risk_score,
                next_2h_probability,
                blockage_score,
                rainfall_used_mm_hr,
                rainfall_source,
                status,
                image_name,
                image_bytes
            FROM submissions
            ORDER BY submitted_at DESC
            """
        ).fetchall()

    items = []
    for row in rows:
        submitted_at = datetime.fromisoformat(str(row["submitted_at"]))
        items.append(
            {
                "id": int(row["id"]),
                "submitted_at": submitted_at,
                "submitted_at_str": submitted_at.strftime("%Y-%m-%d %H:%M UTC"),
                "contributor_name": row["contributor_name"],
                "contributor_id": row["contributor_id"],
                "selected_area": row["selected_area"],
                "nearest_area": row["nearest_area"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "risk_label": row["risk_label"],
                "risk_score": float(row["risk_score"]),
                "next_2h_probability": float(row["next_2h_probability"]),
                "blockage_score": float(row["blockage_score"]),
                "rainfall_used_mm_hr": float(row["rainfall_used_mm_hr"]),
                "rainfall_source": row["rainfall_source"],
                "status": row["status"],
                "image_name": row["image_name"],
                "image_bytes": row["image_bytes"],
            }
        )
    return items


def update_submission_status(submission_id: int, status: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE submissions SET status = ? WHERE id = ?",
            (status, submission_id),
        )
        conn.commit()


def clear_submissions() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM submissions")
        conn.commit()
