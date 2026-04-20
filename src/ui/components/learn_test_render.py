"""
TEST State Renderer
===================
Complete rendering logic for the TEST state - the quiz/assessment view.

This module handles:
- Progress bar with question counter
- Question and answer display
- Answer button handling
- Keyboard shortcuts (1-4 for A-D)
- State transition to FEEDBACK
"""

import streamlit as st
from pathlib import Path

from src.core.generators import get_raw_context_data, generate_questions_background
from src.managers.state_manager import save_full_state
from src.managers.models_manager import resolve_model_id
from src.ui.components.shared_components import (
    render_lesson_title, 
    handle_skip, 
    render_mark_previous_button,
    render_test_progress_bar,
    render_question,
    render_answer_options,
    render_answer_buttons,
    render_keyboard_hint)
from src.managers.cache_manager import remove_question_from_pool, update_question_in_pool, get_questions_for_test, clear_pool

# =============================================================================
# Entry Point
# =============================================================================

def render_test_state(tutor, adapter):
    """
    Render the complete TEST state view.
    
    This is the quiz view where users answer questions to verify mastery.
    
    Flow:
    1. Check regenerating_test flag — if set, regenerate questions and return
    2. Validate questions exist (redirect to CARD if not)
    3. Render test header with action buttons and lesson title
    4. Render progress bar, question, answer options and buttons
    5. Transition to FEEDBACK when last question is answered
    
    Args:
        tutor: SimpleTutor instance with course state
        adapter: API adapter for content generation
    """

    current = tutor.get_current_element() 
    
    # Validate questions exist
    if st.session_state.get('regenerating_test', False):
        _handle_test_regeneration(tutor, adapter)
        return
    if not st.session_state.questions:
        tutor.state = 'CARD'
        st.rerun()
    
    # === LESSON HEADER ===
    _render_test_header(tutor, current)

    # === TEST UI ===
    _render_test_ui(tutor)

# =============================================================================
# Header
# =============================================================================

def _render_test_header(tutor, current):
    """Render action bar and title for TEST state."""
    current_type = current.get('type', '')
    if current_type in ('module_synthesis', 'module_checkpoint'):
        _render_module_test_action_buttons(tutor)
    else:
        _render_test_action_buttons(tutor)
    render_lesson_title(current.get('lesson_title', ''))

def _render_test_action_buttons(tutor):
    """
    Render action buttons for standard lesson TEST state.

    Left group (content): regenerate pool, source preview, delete question.
    Right group (flow):   mark previous as passed, skip & mark as passed.
    """
    curr_key = Path(st.session_state.current_course_path).name \
        if st.session_state.current_course_path else "unknown"
    current  = tutor.syllabus.get(tutor.current_id, {})
    source   = current.get("lesson_source", "")

    col_left, _, col_right = st.columns([4, 4, 2])

    with col_left:
        b1, b2, b3, b4 = st.columns(4)

        with b1:
            _elem    = tutor.syllabus.get(tutor.current_id, {})
            _lc      = _elem.get("lesson_content", [])
            _default_count = max(1, sum(b.get("questions", 0) for b in _lc) if isinstance(_lc, list) else 5)
            if not st.session_state.get('api_adapter'):
                st.button("", icon=":material/auto_awesome:", help="No API connection",
                          use_container_width=True, disabled=True)
            else:
                with st.popover("", icon=":material/auto_awesome:", help="Regenerate test questions",
                                use_container_width=True):
                    st.caption("Replace the question pool for this lesson with a fresh batch.")
                    st.caption("SRS scheduling for these cards will be cleared.")
                    regen_count = st.number_input(
                        "Number of questions",
                        min_value=1, max_value=50,
                        value=_default_count,
                        key="test_regen_count",
                    )
                    regen_special = st.text_area(
                        "Special requests",
                        placeholder="e.g. Focus on relations between X and Y, ask more about Z",
                        key="test_regen_special",
                    )
                    if st.button("Regenerate", icon=":material/auto_awesome:", type="primary",
                                 use_container_width=True, key="test_regen_confirm"):
                        _handle_test_regenerate(tutor, curr_key, regen_count, regen_special)

        with b2:
            with st.popover("", icon=":material/description:", help="Show source material",
                            use_container_width=True):
                if source:
                    st.markdown(source)
                else:
                    st.caption("No source material available.")
                from src.ui.components.media_render import _media_render
                _media_render(curr_key, tutor.current_id, key_prefix="popover")

        with b3:
            idx = st.session_state.get("current_question_idx", 0)
            _qs = st.session_state.get("questions") or []
            _q  = _qs[idx] if idx < len(_qs) else {}
            _correct_letter = _q.get("correct", "A")
            with st.popover("", icon=":material/edit:", help="Edit this question",
                            use_container_width=True):
                st.caption("Fix a wording issue or factual error in this question.")
                st.caption("Only the question text and correct answer are editable. "
                           "Distractors (B, C, D) and SRS scheduling are not affected.")
                new_q_text = st.text_area(
                    "Question",
                    value=_q.get("question", ""),
                    key=f"edit_q_text_{idx}",
                )
                new_a_text = st.text_area(
                    "Correct answer",
                    value=_q.get("options", {}).get(_correct_letter, ""),
                    key=f"edit_q_answer_{idx}",
                )
                if st.button("Save", icon=":material/save:", type="primary",
                             use_container_width=True, key="test_edit_confirm"):
                    _handle_edit_question(tutor, curr_key, idx, new_q_text, new_a_text)

        with b4:
            with st.popover("", icon=":material/delete:", help="Remove this question permanently",
                            use_container_width=True,
                            disabled=st.session_state.get('is_cloud', False)):
                st.caption("Remove this question permanently? This cannot be undone.")
                if st.button("Delete", icon=":material/delete_forever:", type="primary",
                             use_container_width=True, key="test_del_confirm"):
                    _handle_delete_question(tutor, curr_key)

    with col_right:
        b4, b5 = st.columns(2)

        with b4:
            render_mark_previous_button(tutor)

        with b5:
            if st.button("", icon=":material/step_into:", help="Skip test & mark as passed",
                         key="test_skip", use_container_width=True):
                handle_skip(tutor)

def _render_module_test_action_buttons(tutor):
    """Render action buttons for TEST state on module synthesis — no regenerate."""
    curr_key = Path(st.session_state.current_course_path).name \
        if st.session_state.current_course_path else "unknown"

    # Source preview must show the originating lesson's content, not the checkpoint element
    idx       = st.session_state.get("current_question_idx", 0)
    questions = st.session_state.get("questions") or []
    q         = questions[idx] if idx < len(questions) else {}
    source_id = q.get("source", tutor.current_id)
    source    = tutor.syllabus.get(source_id, {}).get("lesson_source", "")

    col_left, _, col_right = st.columns([3, 5, 2])

    with col_left:
        b1, b2, b3 = st.columns(3)

        with b1:
            with st.popover("", icon=":material/description:", help="Show source material",
                            use_container_width=True):
                if source:
                    st.markdown(source)
                else:
                    st.caption("No source material available.")

        with b2:
            _idx = st.session_state.get("current_question_idx", 0)
            _qs2 = st.session_state.get("questions") or []
            _q2  = _qs2[_idx] if _idx < len(_qs2) else {}
            _cl2 = _q2.get("correct", "A")
            with st.popover("", icon=":material/edit:", help="Edit this question",
                            use_container_width=True):
                st.caption("Fix a wording issue or factual error in this question.")
                st.caption("Only the question text and correct answer are editable. "
                           "Distractors (B, C, D) and SRS scheduling are not affected.")
                new_q_text2 = st.text_area(
                    "Question",
                    value=_q2.get("question", ""),
                    key=f"edit_q_text_{_idx}",
                )
                new_a_text2 = st.text_area(
                    "Correct answer",
                    value=_q2.get("options", {}).get(_cl2, ""),
                    key=f"edit_q_answer_{_idx}",
                )
                if st.button("Save", icon=":material/save:", type="primary",
                             use_container_width=True, key="test_edit_confirm"):
                    _handle_edit_question(tutor, curr_key, _idx, new_q_text2, new_a_text2)

        with b3:
            with st.popover("", icon=":material/delete:", help="Remove this question permanently",
                            use_container_width=True,
                            disabled=st.session_state.get('is_cloud', False)):
                st.caption("Remove this question permanently? This cannot be undone.")
                if st.button("Delete", icon=":material/delete_forever:", type="primary",
                             use_container_width=True, key="test_del_confirm"):
                    _handle_delete_question(tutor, curr_key)

    with col_right:
        b3, b4 = st.columns(2)

        with b3:
            render_mark_previous_button(tutor)

        with b4:
            if st.button("", icon=":material/step_into:", help="Skip test & mark as passed",
                         key="test_skip", use_container_width=True):
                handle_skip(tutor)

def _handle_test_regenerate(tutor, course_key, custom_count=None, special_instructions=None):
    """
    Regenerate ONLY the test questions, preserve card content.

    Clears the question pool from disk and session state, then sets
    regenerating_test flag so the next render triggers _handle_test_regeneration.

    Args:
        tutor:                SimpleTutor instance
        course_key:           Course filename used as cache key
        custom_count:         Override number of questions to generate (None = use formula default)
        special_instructions: Extra prompt instructions (e.g. "focus on X and Y")
    """
    # Store user overrides so _handle_test_regeneration can pick them up
    st.session_state.regen_custom_count        = custom_count
    st.session_state.regen_special_instructions = special_instructions or ""

    # Clear question pool for this lesson
    clear_pool(course_key, tutor.current_id)

    # Clear session state questions
    st.session_state.questions = None
    st.session_state.future_questions = None
    st.session_state.answers = None
    st.session_state.current_question_idx = 0

    # Return to CARD to regenerate test
    st.session_state.regenerating_test = True
    save_full_state()
    st.rerun()

def _handle_delete_question(tutor, course_key):
    """Remove current question from pool and advance to next."""
    idx = st.session_state.current_question_idx
    questions = st.session_state.questions or []

    if not questions or idx >= len(questions):
        return

    current_q = questions[idx]

    # Remove from disk pool — use source field if present (mastery), else current lesson
    element_id = current_q.get('source', tutor.current_id)
    remove_question_from_pool(course_key, element_id, current_q)

    # Remove from active session list
    st.session_state.questions.pop(idx)

    # Clamp index so we don't fall off the end
    if st.session_state.questions:
        st.session_state.current_question_idx = min(idx, len(st.session_state.questions) - 1)
    else:
        st.session_state.questions = None

    st.rerun()

def _handle_edit_question(tutor, course_key, idx, new_question_text, new_correct_text):
    """Save edited question text and correct-answer text to session state and disk pool."""
    questions = st.session_state.questions or []
    if idx >= len(questions):
        return

    q = questions[idx]
    correct_letter = q.get("correct", "A")
    element_id = q.get("source", tutor.current_id)
    target_id  = q.get("target_id")

    # Update session state in-place so the current test reflects the edit immediately
    q["question"] = new_question_text
    q["options"][correct_letter] = new_correct_text

    # Persist to disk pool
    update_question_in_pool(course_key, element_id, target_id, new_question_text, new_correct_text)

    st.rerun()


# =============================================================================
# Test UI
# =============================================================================

def _render_test_ui(tutor):
    """Render the complete test UI with progress, question, and answers."""
    idx = st.session_state.current_question_idx
    total_q = len(st.session_state.questions)
    
    # Check if test complete
    if idx >= total_q:
        tutor.state = 'FEEDBACK'
        st.rerun()
    
    q = st.session_state.questions[idx]
    
    # === PROGRESS BAR ===
    render_test_progress_bar(idx, total_q)
    
    # === QUESTION ===
    render_question(q)
    
    # === ANSWER OPTIONS ===
    render_answer_options(q)
    
    # === ANSWER BUTTONS ===
    render_answer_buttons(idx, total_q,
        on_complete=lambda: setattr(tutor, 'state', 'FEEDBACK'))
    
    # === KEYBOARD HINT ===
    render_keyboard_hint('answers')

# =============================================================================
# Loading & Regeneration
# =============================================================================

def _handle_test_regeneration(tutor, adapter):
    """
    Regenerate test questions synchronously while showing a spinner.

    Called when regenerating_test flag is set — bypasses normal TEST render
    and generates a fresh question pool for the current lesson from scratch.

    Args:
        tutor: SimpleTutor instance
        adapter: API adapter for question generation
    """
    
    if not adapter:
        st.warning("No API connection — cannot regenerate questions.", icon=":material/wifi_off:")
        st.session_state.regenerating_test = False
        st.rerun()
        return

    with st.spinner("Generating fresh questions..."):
        course_filename = Path(st.session_state.current_course_path).name \
            if st.session_state.current_course_path else None
        
        test_cnt = tutor.get_test_count(st.session_state.test_counts)
        content_to_show = get_raw_context_data(
            tutor.syllabus, tutor.current_id,
            st.session_state.get('lesson_context_window', 3)
        )

        
        # Capture session state values
        model_id = resolve_model_id(st.session_state.active_provider, st.session_state.selected_models['questions'])
        prompt_instruction = st.session_state.custom_prompts['questions']
        _elem = tutor.syllabus.get(tutor.current_id, {})
        _lc = _elem.get('lesson_content', [])
        _pool_size = sum(b.get('questions', 0) for b in _lc) if isinstance(_lc, list) else None
        _block_id = _elem.get('source_ids', ['UNKNOWN'])[0]

        # Use user-supplied count if provided, otherwise fall back to formula default
        _custom_count   = st.session_state.pop("regen_custom_count", None)
        _special        = st.session_state.pop("regen_special_instructions", "")
        _effective_pool = _custom_count if _custom_count else (_pool_size or None)

        def generate_pool():
            return generate_questions_background(
                content_to_show,
                adapter,
                model_id,
                prompt_instruction,
                course_filename,
                _block_id,
                count=_effective_pool,
                special_instructions=_special or None,
            )

        _lesson_cap = st.session_state.get('lesson_max_questions', 0) or 999
        st.session_state.questions = get_questions_for_test(
            course_filename,
            tutor.current_id,
            _lesson_cap,
            generate_pool,
        )
        
        # Reset test state
        st.session_state.answers = [None] * len(st.session_state.questions)
        st.session_state.current_question_idx = 0
        st.session_state.regenerating_test = False
        
        st.rerun()
