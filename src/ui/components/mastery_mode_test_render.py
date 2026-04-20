"""
Mastery Mode Test Renderer
==========================
Renders the mastery range test — a cross-lesson test drawn from
selected lesson pools. Shares all test components with the standard
learn flow via shared_components, but redirects to MASTERY_FEEDBACK
instead of FEEDBACK on completion.
"""

import streamlit as st
from pathlib import Path

from src.managers.cache_manager import remove_question_from_pool, update_question_in_pool
from src.ui.components.mastery_feedback_render import terminate_mastery_batch
from src.ui.components.shared_components import (
    render_test_header,
    render_test_progress_bar,
    render_question,
    render_answer_options,
    render_answer_buttons,
    render_keyboard_hint,
)

def render_mastery_test(tutor):
    """
    Render the mastery range test.

    Shares all test components with the standard learn flow via
    shared_components, but redirects to MASTERY_FEEDBACK on completion
    and shows a mastery-specific lesson source caption below the progress bar.

    """
    # =========================================================================
    # Logic
    # =========================================================================

    # Guard: no questions → back to setup
    if not st.session_state.get('questions'):
        tutor.state = 'MASTERY_SETUP'
        st.rerun()

    idx     = st.session_state.current_question_idx
    total_q = len(st.session_state.questions)

    # Guard: all questions answered → transition to mastery feedback
    if idx >= total_q:
        if not st.session_state.get('mastery_questions'):
            st.session_state.mastery_questions = list(st.session_state.questions)
        tutor.state = 'MASTERY_FEEDBACK'
        st.rerun()

    # Resolve current question and its source lesson title
    q           = st.session_state.questions[idx]
    source_id   = q.get('source', '')
    source_data = tutor.syllabus.get(source_id, {})
    title       = source_data.get('lesson_title', source_id)

    selected_ids = st.session_state.get('mastery_selected_ids', [])
    lesson_count = len(selected_ids)

    def _on_complete():
        st.session_state.mastery_questions = list(st.session_state.questions)
        tutor.state = 'MASTERY_FEEDBACK'

    # =========================================================================
    # UI
    # =========================================================================

    def _delete_q():
        course_name = Path(st.session_state.get("current_course_path", "")).name
        remove_question_from_pool(course_name, source_id, q)
        questions = st.session_state.questions or []
        questions.pop(idx)
        st.session_state.questions = questions
        if questions:
            st.session_state.current_question_idx = min(idx, len(questions) - 1)
            st.session_state.answers = st.session_state.answers[:len(questions)]
        else:
            tutor.state = "MASTERY_FEEDBACK"
        st.rerun()

    # Header — back button | source popover | delete | lesson title
    _course_filename = Path(st.session_state.get("current_course_path", "")).name
    def _edit_q(new_q_text, new_a_text):
        correct_letter = q.get("correct", "A")
        q["question"] = new_q_text
        q["options"][correct_letter] = new_a_text
        update_question_in_pool(_course_filename, source_id, q.get("target_id", ""), new_q_text, new_a_text)
        st.rerun()

    if render_test_header(
        title, source_data.get("lesson_source", ""), "mastery_test",
        on_delete=_delete_q,
        on_edit=_edit_q,
        edit_question=q,
        course_filename=_course_filename,
        lesson_id=source_id,
    ):
        terminate_mastery_batch(tutor)

    # Progress bar + mastery-specific scope caption
    render_test_progress_bar(idx, total_q)
    st.caption(f"Testing across {lesson_count} lesson{'s' if lesson_count != 1 else ''}")

    # Question
    render_question(q)

    # Answer options (display)
    render_answer_options(q)

    # Answer buttons (interaction) — calls _on_complete on last question
    render_answer_buttons(idx, total_q, on_complete=_on_complete)

    # Keyboard hint
    render_keyboard_hint('answers')