"""
SRS Manager
===========
All SRS persistence in one place:

  data/srs_data/srs.db          — SQLite schedule database (WAL mode)
  data/srs_data/srs_settings.json — display settings: course groups

Schema
------
cards (course_name TEXT, block_id TEXT, lesson_id TEXT,
        due TEXT, stability REAL, difficulty REAL,
        step INT, state INT, last_review TEXT,
        PRIMARY KEY (course_name, block_id))

Identifiers
-----------
  course_name — filename, e.g. "World_War_I.json"
  block_id    — sentence ID, e.g. "P001_S03"  (1-to-1 with a question after
                the pool-size refactor; stable across pool regeneration)
  lesson_id   — element ID, e.g. "L01"        (for journey navigation)

Thread safety
-------------
SRS writes happen only in the main Streamlit thread (feedback render).
Background prefetch threads never touch srs.db. SQLite WAL + context
managers are sufficient.
"""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import streamlit as st
from src.core.srs_engine import review_card, new_card_dict
from src.utils.logger import get_logger

_log = get_logger("srs")

# ============================================================================
# PATHS
# ============================================================================

SRS_DATA_DIR   = Path("data/srs_data")
SRS_DB_PATH    = SRS_DATA_DIR / "srs.db"
SRS_SETTINGS_PATH = SRS_DATA_DIR / "srs_settings.json"


# ============================================================================
# DB HELPERS
# ============================================================================

def _get_conn() -> sqlite3.Connection:
    SRS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SRS_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables and indexes if they don't exist. Idempotent."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                course_name TEXT NOT NULL,
                block_id    TEXT NOT NULL,
                lesson_id   TEXT NOT NULL,
                due         TEXT NOT NULL,
                stability   REAL    DEFAULT NULL,
                difficulty  REAL    DEFAULT NULL,
                step        INTEGER DEFAULT 0,
                state       INTEGER DEFAULT 0,
                last_review TEXT,
                PRIMARY KEY (course_name, block_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_due    ON cards(due)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_course ON cards(course_name)")
        conn.commit()


# ============================================================================
# QUESTION LOOKUP
# ============================================================================

# Sentinel: returned when the question pool file could not be read (IO/parse error).
# Distinct from None (= file read OK, question genuinely absent from pool).
_LOOKUP_ERROR = object()


def _get_question_for_card(course_name: str, lesson_id: str, block_id: str):
    """
    Find the question whose target_id == block_id inside lesson_id's pool.

    Returns:
        dict            — question found
        None            — file read OK but question not in pool (confirmed ghost)
        _LOOKUP_ERROR   — IO / parse error; caller must NOT delete the card
    """
    stem = Path(course_name).stem
    path = Path("data/course_data") / stem / f"{stem}_questions.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            pools = json.load(f)
    except Exception as e:
        _log.warning("question lookup IO error course=%s lesson=%s block=%s: %s", course_name, lesson_id, block_id, e)
        return _LOOKUP_ERROR

    for q in pools.get(lesson_id, {}).get("pool", []):
        if q.get("target_id") == block_id:
            return q
    return None  # file read successfully — question is genuinely absent


# ============================================================================
# CORE WRITE OPERATIONS
# ============================================================================

def record_answers_batch(
    course_name: str,
    lesson_id:   str,
    questions:   list,
    answers:     list,
) -> None:
    """
    Record FSRS reviews for every question answered in a normal-flow test.

    Called from learn_feedback_render.py exactly once per FEEDBACK visit
    (guarded by srs_recorded_current session flag to prevent double-write).

    Args:
        course_name: e.g. "World_War_I.json"
        lesson_id:   e.g. "L01"
        questions:   list of question dicts (each has 'target_id' and 'correct')
        answers:     list of user answer letters ("A"–"D" or None)
    """
    if not course_name or not questions:
        return

    init_db()

    with _get_conn() as conn:
        for q, ans in zip(questions, answers):
            block_id = q.get("target_id")
            if not block_id:
                continue
            was_correct = (ans is not None and ans == q.get("correct"))

            row = conn.execute(
                "SELECT * FROM cards WHERE course_name = ? AND block_id = ?",
                (course_name, block_id),
            ).fetchone()

            card_dict = dict(row) if row else new_card_dict()
            updated   = review_card(card_dict, was_correct)

            conn.execute(
                """
                INSERT OR IGNORE INTO cards
                    (course_name, block_id, lesson_id,
                     due, stability, difficulty, step, state, last_review)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    course_name, block_id, lesson_id,
                    updated["due"], updated["stability"], updated["difficulty"],
                    updated["step"], updated["state"], updated["last_review"],
                ),
            )
        conn.commit()


def record_srs_answers_batch(questions: list, answers: list) -> None:
    """
    Record FSRS reviews for a completed SRS test batch.

    Questions carry '_srs_meta' dicts injected by SrsTutor.load_batch(),
    containing course_name, block_id, lesson_id for each card.

    Args:
        questions: list of question dicts with '_srs_meta' field
        answers:   list of user answer letters
    """
    if not questions:
        return

    init_db()

    with _get_conn() as conn:
        for q, ans in zip(questions, answers):
            meta = q.get("_srs_meta")
            if not meta:
                continue
            course_name = meta["course_name"]
            block_id    = meta["block_id"]
            lesson_id   = meta["lesson_id"]
            was_correct = (ans is not None and ans == q.get("correct"))

            row = conn.execute(
                "SELECT * FROM cards WHERE course_name = ? AND block_id = ?",
                (course_name, block_id),
            ).fetchone()

            card_dict = dict(row) if row else new_card_dict()
            updated   = review_card(card_dict, was_correct)

            conn.execute(
                """
                INSERT OR REPLACE INTO cards
                    (course_name, block_id, lesson_id,
                     due, stability, difficulty, step, state, last_review)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    course_name, block_id, lesson_id,
                    updated["due"], updated["stability"], updated["difficulty"],
                    updated["step"], updated["state"], updated["last_review"],
                ),
            )
        conn.commit()


def delete_card(course_name: str, block_id: str) -> None:
    """Remove a single SRS card (called when user deletes a question from the pool)."""
    try:
        init_db()
        with _get_conn() as conn:
            conn.execute(
                "DELETE FROM cards WHERE course_name = ? AND block_id = ?",
                (course_name, block_id),
            )
            conn.commit()
    except Exception as e:
        _log.error("delete_card failed course=%s block=%s: %s", course_name, block_id, e)
        st.toast("SRS card could not be removed.", icon=":material/warning:")


def reset_srs(course_name: str) -> None:
    """Delete all SRS schedule data for one course (does NOT touch _questions.json)."""
    try:
        init_db()
        with _get_conn() as conn:
            conn.execute("DELETE FROM cards WHERE course_name = ?", (course_name,))
            conn.commit()
    except Exception as e:
        _log.error("reset_srs failed course=%s: %s", course_name, e)
        st.toast("SRS reset failed.", icon=":material/warning:")


# ============================================================================
# QUERY OPERATIONS
# ============================================================================

def _get_study_day_end() -> str:
    """
    UTC ISO timestamp for the end of the current study day.

    Study day runs 04:00 local → 04:00 local next day.
    Using local 4 AM as the rollover (instead of midnight or now) means:
      - The full day's cards are visible from 04:01 onward — no stragglers
        appearing mid-session because their scheduled time passed while studying.
      - Late-night reviewers (00:00–03:59) still see yesterday's batch,
        not tomorrow's cards.
      - Past-due cards from missed days are always included because their
        timestamps are before study_day_end regardless of rollover.

    No schema change required — UTC timestamps in the DB are untouched.
    """
    now_local = datetime.now().astimezone()
    today_4am = now_local.replace(hour=4, minute=0, second=0, microsecond=0)
    if now_local < today_4am:
        day_end = today_4am                   # before 4 AM — still in yesterday's session
    else:
        day_end = today_4am + timedelta(days=1)  # after 4 AM — session ends tomorrow 4 AM
    return day_end.astimezone(timezone.utc).isoformat()


def get_due_cards(course_names: Optional[list] = None) -> list:
    """
    Return all due cards (due <= now), enriched with their question dict.

    Cards whose question no longer exists in the pool are silently skipped.

    Args:
        course_names: Filter to these courses. None = all courses.

    Returns:
        list of dicts, each containing all DB fields plus 'question' key.
        Order: ascending due date (oldest due first).
    """
    try:
        init_db()
        cutoff = _get_study_day_end()

        with _get_conn() as conn:
            if course_names:
                placeholders = ",".join("?" * len(course_names))
                rows = conn.execute(
                    f"SELECT * FROM cards WHERE due <= ? AND course_name IN ({placeholders}) ORDER BY due",
                    [cutoff] + list(course_names),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cards WHERE due <= ? ORDER BY due",
                    (cutoff,),
                ).fetchall()

        ghost_keys = []
        result = []
        for row in rows:
            d = dict(row)
            q = _get_question_for_card(d["course_name"], d["lesson_id"], d["block_id"])
            if q is _LOOKUP_ERROR:
                continue  # IO error — skip but never delete
            if q is None:
                ghost_keys.append((d["course_name"], d["block_id"]))  # confirmed ghost
                continue
            # Embed SRS metadata inside the question for easy access in renderers
            q_copy = q.copy()
            q_copy["_srs_meta"] = {
                "course_name": d["course_name"],
                "block_id":    d["block_id"],
                "lesson_id":   d["lesson_id"],
            }
            d["question"] = q_copy
            result.append(d)

        if ghost_keys:
            with _get_conn() as conn:
                for course_name, block_id in ghost_keys:
                    conn.execute(
                        "DELETE FROM cards WHERE course_name = ? AND block_id = ?",
                        (course_name, block_id),
                    )
                    _log.info("deleted ghost SRS card course=%s block=%s", course_name, block_id)
                conn.commit()

        return result
    except Exception as e:
        _log.error("get_due_cards failed: %s", e)
        return []


def get_due_count(course_names: Optional[list] = None) -> int:
    """Fast due-card count for badges (no question lookup)."""
    try:
        init_db()
        cutoff = _get_study_day_end()
        with _get_conn() as conn:
            if course_names:
                placeholders = ",".join("?" * len(course_names))
                row = conn.execute(
                    f"SELECT COUNT(*) FROM cards WHERE due <= ? AND course_name IN ({placeholders})",
                    [cutoff] + list(course_names),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM cards WHERE due <= ?",
                    (cutoff,),
                ).fetchone()
        return row[0] if row else 0
    except Exception as e:
        _log.error("get_due_count failed: %s", e)
        return 0


def get_due_count_per_course() -> dict:
    """
    Return {course_name: due_count} for all courses that have any due cards.
    Used by srs_render.py to show per-deck badges.
    """
    try:
        init_db()
        cutoff = _get_study_day_end()
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT course_name, COUNT(*) as cnt FROM cards WHERE due <= ? GROUP BY course_name",
                (cutoff,),
            ).fetchall()
        return {row["course_name"]: row["cnt"] for row in rows}
    except Exception as e:
        _log.error("get_due_count_per_course failed: %s", e)
        return {}


def get_total_card_count_per_course() -> dict:
    """Return {course_name: total_cards} for all courses in the DB."""
    try:
        init_db()
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT course_name, COUNT(*) as cnt FROM cards GROUP BY course_name"
            ).fetchall()
        return {row["course_name"]: row["cnt"] for row in rows}
    except Exception as e:
        _log.error("get_total_card_count_per_course failed: %s", e)
        return {}


# ============================================================================
# SETTINGS (groups for srs_render.py)
# ============================================================================

def load_settings() -> dict:
    """
    Load SRS display settings.

    Returns:
        dict with key 'groups': {group_name: [course_filename, ...]}
    """
    if not SRS_SETTINGS_PATH.exists():
        return {"groups": {}}
    try:
        with open(SRS_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log.warning("load_settings failed: %s", e)
        return {"groups": {}}


def save_settings(settings: dict) -> None:
    """Persist SRS display settings to disk."""
    SRS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(SRS_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log.error("save_settings failed: %s", e)
        st.toast("SRS settings could not be saved.", icon=":material/warning:")
