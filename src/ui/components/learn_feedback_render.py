"""
FEEDBACK State Renderer
=======================
Complete rendering logic for the FEEDBACK state - test results and review.

This module handles:
- Score summary cards (score, accuracy, pass/fail status)
- Action buttons (continue/retry/return)
- Detailed question-by-question review
- Answer comparison (correct vs incorrect)
- Explanations with insights
"""

import streamlit as st
from pathlib import Path

from src.managers.state_manager import save_full_state, full_reset
from src.managers.srs_manager import record_answers_batch
from src.managers.cache_manager import _reshuffle_options
from src.ui.components.shared_components import (
    render_score_summary_cards,
    render_answer_review_list,
    render_keyboard_hint,
    )

# =============================================================================
# Main Entry Point
# =============================================================================

def render_feedback_state(tutor):
    """
    Render the complete FEEDBACK state view.
    
    This is the results view shown after completing a test.
    
    Flow:
    1. Calculate score and accuracy
    2. Display summary cards (score, accuracy, status)
    3. Show action buttons (continue/retry/return)
    4. Display detailed review with answer comparisons
    5. Handle state transitions
    
    Args:
        tutor: SimpleTutor instance with course state
    """
    # === SCORE CALCULATION ===
    correct, total, pct = _calculate_score()

    # === RECORD SRS (once per visit, normal learn flow only) ===
    elem_type = tutor.get_current_element().get('type', 'lesson')
    _srs_eligible = (
        not st.session_state.get('is_quick_test')
        and elem_type == 'lesson'
    )
    if _srs_eligible and not st.session_state.get('is_cloud'):
        record_key = f"srs_recorded_{tutor.current_id}"
        if not st.session_state.get(record_key):
            course_filename = Path(st.session_state.current_course_path).name \
                if st.session_state.current_course_path else None
            record_answers_batch(
                course_filename,
                tutor.current_id,
                st.session_state.questions or [],
                st.session_state.answers or [],
            )
            st.session_state[record_key] = True

    # === SUMMARY CARDS ===
    render_score_summary_cards(correct, total, pct, tutor.current_id)
    
    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
    
    # === ACTION BUTTONS ===
    _render_action_buttons(pct, tutor)
    
    st.divider()
    
    # === DETAILED REVIEW ===
    render_answer_review_list(st.session_state.questions, st.session_state.answers, syllabus=st.session_state.tutor.syllabus)


# =============================================================================
# Score
# =============================================================================

def _calculate_score():
    """
    Calculate test results.
    
    Returns:
        tuple: (correct_count, total_questions, percentage)
    """
    correct = sum(
        1 for q, a in zip(st.session_state.questions, st.session_state.answers)
        if a == q['correct']
    )
    total = len(st.session_state.questions)
    pct = (correct / total) * 100 if total > 0 else 0
    
    return correct, total, pct

# =============================================================================
# Action Buttons
# =============================================================================

def _render_action_buttons(pct, tutor):
    """
    Render action buttons based on test result and mode.
    
    Buttons shown:
    - Quick test: Retake / Return to course
    - Passed (≥80%): Continue journey
    - Failed (<80%), standard: Retry assessment
    - Failed (<80%), checkpoint/synthesis/final: Mastery Journey + Retake
    """
    # A. Quick Test Return
    if st.session_state.is_quick_test:
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "Retake Test",
                icon=":material/replay:",
                type="primary",
                use_container_width=True,
                key="quick_test_retake",
            ):
                st.session_state.questions = None
                st.session_state.answers = None
                st.session_state.current_question_idx = 0
                st.session_state.regenerating_test = True
                tutor.state = 'CARD'
                st.rerun()
            render_keyboard_hint('retake')
        with col2:
            if st.button(
                "Return to Course",
                icon=":material/arrow_back:",
                type="secondary",
                use_container_width=True
            ):
                st.session_state.is_quick_test = False
                tutor.state = 'CARD'
                full_reset()
                st.rerun()
            render_keyboard_hint('backspace')
    
    # B. Standard Flow
    else:
        if pct >= 80:          
            if not st.session_state.get('balloons_shown'):
                st.balloons()
                st.session_state.balloons_shown = True
            _render_continue_button(tutor)

    
        
        else:
            elem_type = tutor.get_current_element().get('type', 'lesson')
            if elem_type in ('module_synthesis', 'module_checkpoint', 'final_test'):
                _render_checkpoint_failed_buttons(tutor)
            else:
                _render_retry_button(tutor, elem_type=elem_type)


def _render_continue_button(tutor):
    """
    Render continue button for passed tests.

    Handles:
    - Moving to next lesson
    - Saving progress
    - Showing keyboard hint while waiting
    """
    btn_next = st.button(
        "Continue Journey",
        icon=":material/arrow_forward:",
        type="primary",
        use_container_width=True
    )
    
    if btn_next:
        if tutor.current_id == 'FINAL_TEST':
            # Course complete — no next element exists; return to welcome screen
            full_reset()
            st.session_state.tutor = None
        else:
            tutor.move_to_next()
            full_reset()
            save_full_state()
        st.rerun()
    else:
        render_keyboard_hint('continue')


def _render_retry_button(tutor, elem_type='subconcept'):
    """
    Render retry button for failed standard and synthesis assessments.

    For synthesis/checkpoint types, clears the active session and skips
    the card UI via regenerating_test flag — questions are re-sampled
    from existing per-lesson pools, no AI generation occurs.
    For standard lessons, resets to CARD for a fresh attempt.
    """
    is_synthesis = elem_type in ('module_synthesis', 'module_checkpoint')

    if st.button("Retake Test", icon=":material/replay:", type="secondary", use_container_width=True):
        if is_synthesis:
            # Skip the card, go straight back into the test
            st.session_state.questions = None
            st.session_state.regenerating_test = True
            st.session_state.answers = None
            st.session_state.current_question_idx = 0
            tutor.state = 'CARD'
        else:
            # Go straight to TEST with failed questions reshuffled — source text
            # is already readable in the feedback expanders, no need to revisit the card.
            failed = [
                q for q, a in zip(st.session_state.questions, st.session_state.answers)
                if a != q['correct']
            ]
            questions = _reshuffle_options(failed if failed else list(st.session_state.questions))
            full_reset()
            st.session_state.questions = questions
            st.session_state.answers = [None] * len(questions)
            st.session_state.current_question_idx = 0
            tutor.state = 'TEST'
        st.rerun()

    render_keyboard_hint('retake')

def _render_checkpoint_failed_buttons(tutor):
    """Journey + Retake buttons for failed checkpoint/synthesis/final tests."""
    failed_ids = list({
        q.get('source') for q, a in zip(st.session_state.questions, st.session_state.answers)
        if a != q['correct'] and q.get('source')
    })

    st.markdown(
        "### :material/route: Personalized Mastery Journey\n"
        "Let's close those knowledge gaps! We've built a custom review path based on the questions you missed. "
        "Revisit the source material, pass a quick 5-question check to confirm your understanding, and master the topics you struggled with."
    )

    col_journey, col_retry = st.columns([0.6, 0.4])

    with col_journey:
        if st.button(
            f"Begin Journey  ({len(failed_ids)} stops)",
            icon=":material/rocket_launch:",
            type="primary",
            use_container_width=True,
            key="checkpoint_begin_journey"
        ):
            # Store where to return after the journey
            st.session_state.journey_return_to = tutor.current_id
            # Build ordered queue from failed lesson IDs
            queue = [
                {'id': eid, 'mode': 'full'}
                for eid in tutor.syllabus
                if eid in failed_ids
            ]
            st.session_state.mastery_journey_queue = queue
            st.session_state.mastery_journey_idx = 0
            st.session_state.mastery_journey_active = True
            full_reset()
            tutor.state = 'MASTERY_JOURNEY_CARD'
            st.rerun()
        render_keyboard_hint('begin_journey_j')

    with col_retry:
        if st.button(
            "Retake Test",
            icon=":material/replay:",
            use_container_width=True,
            key="checkpoint_retry"
        ):
            st.session_state.questions = None
            st.session_state.answers = None
            st.session_state.current_question_idx = 0
            st.session_state.force_test = True
            tutor.state = 'CARD'
            st.rerun()
        render_keyboard_hint('retake') 