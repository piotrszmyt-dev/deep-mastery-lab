"""
Mastery Feedback Renderer
=========================
Displays results after MASTERY_TEST completes and launches the Mastery Journey.

Flow:
    1. Score summary cards (correct / total / accuracy)
    2. Perfect score → celebration screen, back to setup
    3. Any failures → journey launcher + full answer review

Journey:
    One stop per failed lesson, ordered by syllabus position.
    Each stop: card re-read + mini-test confirmation check.
    Ignored lessons are excluded from the queue.
"""

import streamlit as st

from src.managers.state_manager import save_full_state, full_reset
from src.ui.components.shared_components import (
    render_score_summary_cards,
    render_answer_review_list,
    render_keyboard_hint,
)

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def render_mastery_feedback(tutor):
    """
    Render the Mastery Test results screen.

    Flow:
    1. Guard: redirect to MASTERY_SETUP if no questions found
    2. Pad answers for tests exited early
    3. Evaluate answers → score + wrong-by-source map
    4. Display score summary cards
    5. Perfect score → celebration screen and early return
    6. Failed → journey launcher + full answer review

    Args:
        tutor: SimpleTutor instance
    """
    questions = st.session_state.get('mastery_questions', st.session_state.get('questions', []))
    answers = st.session_state.get('answers', [])

    if not questions:
        st.error("No mastery test data found.")
        if st.button("← Back to Course"):
            _exit_mastery(tutor)
        return

    # Pad answers if test was exited early
    while len(answers) < len(questions):
        answers.append(None)

    correct_count, wrong_by_source = _evaluate_answers(tutor, questions, answers)
    total = len(questions)
    score_pct = (correct_count / total * 100) if total > 0 else 0

    render_score_summary_cards(correct_count, total, score_pct)

    if not wrong_by_source:
        _render_perfect_score(tutor)
        return

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
    _render_journey_launcher(tutor, list(wrong_by_source.keys()))

    st.divider()

    questions = st.session_state.get('mastery_questions', [])
    answers   = st.session_state.get('answers', [])
    render_answer_review_list(questions, answers, syllabus=st.session_state.tutor.syllabus)

# ============================================================================
# EVALUATION
# ============================================================================

def _evaluate_answers(tutor, questions, answers):
    """
    Compare answers to correct answers.

    Returns:
        tuple: (correct_count: int, wrong_by_source: dict)
            wrong_by_source = {source_id: [{'question', 'your_answer', 'correct_answer'}]}
    """
    correct_count = 0
    wrong_by_source = {}

    for q, ans in zip(questions, answers):
        correct = q.get('correct') or q.get('answer', '')
        is_correct = (ans is not None) and (ans.upper() == correct.upper())

        if is_correct:
            correct_count += 1
        else:
            source = q.get('source', tutor.current_id)
            if source not in wrong_by_source:
                wrong_by_source[source] = []
            wrong_by_source[source].append({
                'question': q,
                'your_answer': ans,
                'correct_answer': correct
            })

    return correct_count, wrong_by_source


# ============================================================================
# PERFECT SCORE
# ============================================================================

def _render_perfect_score(tutor):
    """Render the perfect score celebration and 'Take Another Test' button → MASTERY_SETUP."""
    
    st.balloons()

    st.markdown(
        "### :material/workspace_premium: Flawless Mastery!\n"
        "**Perfect score.** You've completely mastered all the selected content with zero gaps in your knowledge. "
        "From here, you can set up a new test for a different range, continue learning new modules, "
        "or simply take a well-deserved break to celebrate your progress!"
    )
    
    st.markdown("<br>", unsafe_allow_html=True)

    if st.button(
        "Take Another Test",
        icon=":material/arrow_back:",
        type="primary",
        use_container_width=True
    ):
        terminate_mastery_batch(tutor)
    render_keyboard_hint("continue")

# ============================================================================
# JOURNEY launcher
# ============================================================================

def _render_journey_launcher(tutor, failed_ids):
    """
    Render the journey launcher: stop count, Begin Journey button,
    and Take Another Test fallback.
    """
    queue = _build_journey_queue(tutor, failed_ids)

    # Journey description paragraph
    st.markdown(
        "### :material/route: Personalized Mastery Journey\n"
        "Let's close those knowledge gaps! We've built a custom review path based on the questions you missed. "
        "Revisit the source material, pass a quick 5-question check to confirm your understanding, and master the topics you struggled with."
    )

    st.markdown(f"**{len(queue)} lessons to revisit** — card review + mini-test for each.")

    st.markdown("<hr style='margin-top: 1em; margin-bottom: 1.5em; opacity: 0.3;'>", unsafe_allow_html=True)

    col_journey, col_retry = st.columns([0.6, 0.4])

    with col_journey:
        if st.button(
            f"Begin Journey  ({len(queue)} stops)",
            icon=":material/rocket_launch:",  
            type="primary",
            use_container_width=True,
            key="mastery_begin_journey"
        ):
            _launch_mastery_journey(tutor, queue)

        render_keyboard_hint('begin_journey_j')

    with col_retry:
        if st.button(
            "Take Another Test",
            icon=":material/bolt:",
            use_container_width=True,
            key="mastery_take_another"
        ):
            terminate_mastery_batch(tutor)
        render_keyboard_hint("continue")

def _build_journey_queue(tutor, failed_ids):
    """
    Build the ordered journey queue from failed lesson IDs.

    Filters out ignored elements and preserves syllabus order.
    Returns a list of {'id': str, 'mode': 'full'} dicts.
    """
    ignored = st.session_state.get('ignored_elements', set())
    eligible = {
        fid for fid in failed_ids
        if fid in tutor.syllabus and fid not in ignored
    }
    return [
        {'id': eid}
        for eid in tutor.syllabus
        if eid in eligible
    ]

def _launch_mastery_journey(tutor, queue):
    """
    Initialize and enter the Mastery Journey.

    Args:
        tutor: SimpleTutor instance
        queue: list of {'id': str} dicts — ordered by syllabus position
    """
    st.session_state.mastery_journey_queue = queue
    st.session_state.mastery_journey_idx = 0
    st.session_state.mastery_journey_active = True

    first = queue[0]
    tutor.current_id = first['id']
    tutor.state = 'MASTERY_JOURNEY_CARD'

    full_reset()
    save_full_state()
    st.rerun()

# ============================================================================
# HELPERS
# ============================================================================

def terminate_mastery_batch(tutor):
    """
    Abort the in-flight mastery batch and return to setup.

    Clears all mid-run state (questions, journey queue, flags) but preserves
    mastery_selected so the user can immediately relaunch with the same
    lesson selection.
    """
    st.session_state.mastery_questions = []
    st.session_state.mastery_journey_queue = []
    st.session_state.mastery_journey_idx = 0
    st.session_state.mastery_journey_active = False
    st.session_state.pop('journey_return_to', None)
    st.session_state.pop('_journey_balloons_shown', None)
    full_reset()
    tutor.state = 'MASTERY_SETUP'
    st.rerun()


def _exit_mastery(tutor):
    """Clean exit from mastery mode back to normal course flow."""
    st.session_state.mastery_journey_active = False
    st.session_state.mastery_journey_queue = []
    st.session_state.mastery_journey_idx = 0
    st.session_state.mastery_questions = []
    st.session_state.mastery_selected = {}
    full_reset()
    tutor.state = 'CARD'
    st.rerun()