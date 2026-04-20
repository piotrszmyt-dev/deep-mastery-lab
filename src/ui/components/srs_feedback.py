"""
SRS Feedback
============
Results screen shown after each batch completes.

Layout:
  1. Score summary cards (correct / total / accuracy)
  2. Message line (perfect / good / needs review)
  3. Action buttons:
       - Any wrong answers  → two columns:
             [Begin Journey  (N stops)]   [Start Next Batch] or [Back to SRS]
       - All correct        → one button:
             [Start Next Batch] or [Back to SRS]
  4. Detailed answer review (shared component)

FSRS recording happens here exactly once per batch, guarded by
st.session_state.srs_batch_recorded to prevent double-write on reruns.
"""

import streamlit as st

from src.managers import srs_manager
from src.managers.state_manager import full_reset
from src.ui.components.shared_components import (
    render_score_summary_cards,
    render_answer_review_list,
    render_keyboard_hint,
)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def render_srs_feedback(srs_tutor):
    """
    Render the SRS batch results screen.

    Args:
        srs_tutor: SrsTutor instance (st.session_state.srs_tutor)
    """
    col_back, _ = st.columns([3, 7])
    with col_back:
        if st.button("", icon=":material/arrow_back:", help="Back",
                     use_container_width=True, key="srs_feedback_back"):
            st.session_state.srs_tutor    = None
            st.session_state.srs_app_open = False
            full_reset()
            st.rerun()

    questions = st.session_state.get("questions") or []
    answers   = st.session_state.get("answers") or []

    # Pad if test was exited early
    while len(answers) < len(questions):
        answers.append(None)

    # ── Record FSRS once per batch ────────────────────────────────────────────
    batch_key = f"srs_batch_recorded_{srs_tutor.batch_number}"
    if not st.session_state.get(batch_key):
        srs_manager.record_srs_answers_batch(questions, answers)
        st.session_state[batch_key] = True

    correct, total, pct = _calculate_score(questions, answers)
    wrong_ids = _collect_wrong_lesson_ids(srs_tutor, questions, answers)

    # ── Score cards ───────────────────────────────────────────────────────────
    render_score_summary_cards(correct, total, pct)
    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # ── Message ───────────────────────────────────────────────────────────────
    if pct == 100:
        st.markdown("**Perfect batch!** All answers correct.")
    elif pct >= 80:
        st.markdown("**Good work.** A few cards need more practice.")
    else:
        st.markdown("**Let's close those knowledge gaps.** Begin the journey or move on.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Action buttons ────────────────────────────────────────────────────────
    _render_action_buttons(srs_tutor, wrong_ids)

    st.divider()

    # Build a minimal syllabus map so render_answer_review_list can show source text
    syllabus = _build_combined_syllabus(srs_tutor, questions)
    render_answer_review_list(questions, answers, syllabus=syllabus)


# ============================================================================
# SCORE HELPERS
# ============================================================================

def _calculate_score(questions, answers):
    correct = sum(
        1 for q, a in zip(questions, answers)
        if a is not None and a == q.get("correct")
    )
    total = len(questions)
    pct   = (correct / total * 100) if total else 0
    return correct, total, pct


def _collect_wrong_lesson_ids(srs_tutor, questions, answers) -> list:
    """
    Return ordered list of (course_name, lesson_id) tuples for wrong answers,
    de-duplicated while preserving first-occurrence order.
    """
    seen  = set()
    stops = []
    for q, a in zip(questions, answers):
        if a is not None and a == q.get("correct"):
            continue
        meta        = q.get("_srs_meta", {})
        course_name = meta.get("course_name", "")
        lesson_id   = meta.get("lesson_id", "")
        if not course_name or not lesson_id:
            continue
        key = (course_name, lesson_id)
        if key not in seen:
            seen.add(key)
            stops.append({"course_name": course_name, "lesson_id": lesson_id})
    return stops


# ============================================================================
# ACTION BUTTONS
# ============================================================================

def _render_action_buttons(srs_tutor, wrong_stops: list):
    has_next    = srs_tutor.has_next_batch()
    has_wrongs  = bool(wrong_stops)

    next_label  = f"Start Next Batch  [{srs_tutor.remaining_due}]" if has_next else "Finish Review"
    next_icon   = ":material/arrow_forward:" if has_next else ":material/done_all:"

    if has_wrongs:
        col_journey, col_next = st.columns([0.6, 0.4])

        with col_journey:
            if st.button(
                f"Begin Journey  ({len(wrong_stops)} stops)",
                icon=":material/route:",
                type="primary",
                use_container_width=True,
                key="srs_begin_journey",
            ):
                _launch_journey(srs_tutor, wrong_stops)
            render_keyboard_hint("begin_journey_j")

        with col_next:
            if st.button(
                next_label,
                icon=next_icon,
                use_container_width=True,
                key="srs_next_batch_btn",
            ):
                _go_next(srs_tutor)
            render_keyboard_hint("continue")
    else:
        if not st.session_state.get("srs_balloons_shown"):
            st.balloons()
            st.session_state.srs_balloons_shown = True

        if st.button(
            next_label,
            icon=next_icon,
            type="primary",
            use_container_width=True,
            key="srs_next_batch_btn",
        ):
            _go_next(srs_tutor)
        render_keyboard_hint("continue")


def _go_next(srs_tutor):
    if srs_tutor.has_next_batch():
        srs_tutor.start_next_batch()
        full_reset()
        srs_tutor.load_batch_into_session(st.session_state)
        st.session_state.srs_app_open = False
        st.rerun()
    else:
        # End of all batches — return to welcome screen
        st.session_state.srs_tutor    = None
        st.session_state.srs_app_open = False
        full_reset()
        st.rerun()


def _launch_journey(srs_tutor, wrong_stops: list):
    """Build the journey queue and enter SRS_JOURNEY_CARD state."""
    st.session_state.srs_journey_queue = wrong_stops
    st.session_state.srs_journey_idx   = 0
    full_reset()
    srs_tutor.state = "SRS_JOURNEY_CARD"
    st.rerun()


# ============================================================================
# SYLLABUS HELPER (for answer review source text)
# ============================================================================

def _build_combined_syllabus(srs_tutor, questions: list) -> dict:
    """
    Build a syllabus dict for render_answer_review_list that supports
    multi-course batches without paragraph ID collisions.

    Paragraph IDs are sequential per-course (P001, P002 … in every course),
    so a flat .update() merge would cause wrong source text to appear when
    two courses share the same PID. The fix: store each course's master_index
    separately under '_course_master_indexes', keyed by course_name. The
    shared '_master_index' is kept for backwards-compat with single-course flows.
    """
    combined = {"_master_index": {}, "_course_master_indexes": {}}
    seen_courses = set()

    for q in questions:
        meta        = q.get("_srs_meta", {})
        course_name = meta.get("course_name", "")
        if not course_name or course_name in seen_courses:
            continue
        seen_courses.add(course_name)

        # Load from srs_tutor's lazy syllabus cache
        syllabus = srs_tutor._syllabi.get(course_name)
        if syllabus is None:
            srs_tutor.get_lesson(course_name, meta.get("lesson_id", ""))
            syllabus = srs_tutor._syllabi.get(course_name, {})

        master = syllabus.get("_master_index", {})
        combined["_master_index"].update(master)           # backwards compat
        combined["_course_master_indexes"][course_name] = master

    return combined
