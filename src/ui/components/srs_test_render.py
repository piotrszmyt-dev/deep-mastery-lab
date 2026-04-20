"""
SRS Test Render
===============
Renders the SRS batch test — one question at a time, same shared components
as the normal learn flow.

Layout:
  - Batch progress bar (e.g. "Question 3 / 20  •  Batch 1 of 3")
  - Source popover (lesson_source raw text)
  - Remove-from-pool button
  - Question display
  - Answer options
  - Answer buttons (A/B/C/D)
  - Keyboard hint

State transitions (set on srs_tutor, re-routed in app.py):
  All questions answered → srs_tutor.state = 'SRS_FEEDBACK'
"""

import streamlit as st
from pathlib import Path

from src.ui.components.shared_components import (
    render_test_progress_bar,
    render_test_header,
    render_question,
    render_answer_options,
    render_answer_buttons,
    render_keyboard_hint,
)
from src.managers.srs_manager import delete_card
from src.managers.cache_manager import remove_question_from_pool, update_question_in_pool


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def render_srs_test(srs_tutor):
    """
    Render the SRS batch test screen.

    Args:
        srs_tutor: SrsTutor instance (st.session_state.srs_tutor)
    """
    questions = st.session_state.get("questions") or []
    answers   = st.session_state.get("answers") or []
    idx       = st.session_state.get("current_question_idx", 0)
    total_q   = len(questions)

    if not questions or idx >= total_q:
        srs_tutor.state = "SRS_FEEDBACK"
        st.rerun()
        return

    q = questions[idx]

    _render_header(q, srs_tutor, idx, total_q)
    render_test_progress_bar(idx, total_q)
    render_question(q)
    render_answer_options(q)
    render_answer_buttons(
        idx, total_q,
        on_complete=lambda: setattr(srs_tutor, "state", "SRS_FEEDBACK"),
    )
    render_keyboard_hint("answers")


# ============================================================================
# HEADER (source popover + delete)
# ============================================================================

def _render_header(q: dict, srs_tutor, idx: int, total_q: int):
    meta    = q.get("_srs_meta", {})
    lesson  = srs_tutor.get_lesson(meta.get("course_name", ""), meta.get("lesson_id", ""))
    source  = lesson.get("lesson_source", "")
    title   = lesson.get("lesson_title", meta.get("lesson_id", ""))

    if render_test_header(
        title, source, "srs_test",
        on_delete=lambda: _delete_question(q, srs_tutor, idx),
        on_edit=lambda new_q, new_a: _edit_question(q, new_q, new_a),
        edit_question=q,
        course_filename=meta.get("course_name"),
        lesson_id=meta.get("lesson_id"),
    ):
        st.session_state.srs_tutor    = None
        st.session_state.srs_app_open = False
        st.session_state.tutor        = None
        st.rerun()


def _delete_question(q: dict, srs_tutor, idx: int):
    """Remove question from both the SRS DB and the question pool, then skip it."""
    meta        = q.get("_srs_meta", {})
    course_name = meta.get("course_name", "")
    block_id    = meta.get("block_id", "")
    lesson_id   = meta.get("lesson_id", "")

    if course_name and block_id:
        delete_card(course_name, block_id)
        remove_question_from_pool(course_name, lesson_id, q)

    questions = st.session_state.questions or []
    questions.pop(idx)
    st.session_state.questions = questions
    if questions:
        st.session_state.current_question_idx = min(idx, len(questions) - 1)
        st.session_state.answers = st.session_state.answers[:len(questions)]
    else:
        srs_tutor.state = "SRS_FEEDBACK"
    st.rerun()


def _edit_question(q: dict, new_question_text: str, new_correct_text: str):
    """Update question text and correct-answer text in session state and disk pool."""
    meta        = q.get("_srs_meta", {})
    course_name = meta.get("course_name", "")
    lesson_id   = meta.get("lesson_id", "")
    target_id   = q.get("target_id", "")
    correct_letter = q.get("correct", "A")

    # Update session state in-place so the current test reflects the edit immediately
    q["question"] = new_question_text
    q["options"][correct_letter] = new_correct_text

    update_question_in_pool(course_name, lesson_id, target_id, new_question_text, new_correct_text)
    st.rerun()


def _render_batch_caption(srs_tutor):
    st.caption(f"Batch {srs_tutor.batch_number} of {srs_tutor.total_batches}")
