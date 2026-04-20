"""
Mastery Journey Renderer
========================
Handles the focused re-learning loop after a Mastery Test.

For each lesson the user failed, the journey queues one stop:
read the lesson card, then answer a single question to confirm understanding.
Passing moves to the next stop. Failing offers a retake or return to the card.

States handled here:
    MASTERY_JOURNEY_CARD  — lesson card with "Start Mini-Test" / "Skip to Next"
    MASTERY_JOURNEY_TEST  — 5-question mini-test from the lesson's pool
    MASTERY_JOURNEY_DONE  — completion screen with stats and exit actions
"""

import streamlit as st
import streamlit.components.v1 as components
import time
from pathlib import Path


from src.managers.state_manager import save_full_state, full_reset
from src.managers.cache_manager import sample_from_pool, get_pool, remove_question_from_pool
from src.ui.components.learn_card_render import _display_lesson_content, _generate_lesson_content
from src.ui.components.mastery_feedback_render import terminate_mastery_batch
from src.ui.components.media_render import _media_render, _media_add_popover

from src.ui.components.shared_components import (
    render_lesson_title,
    render_test_header,
    render_test_progress_bar,
    render_question,
    render_answer_options,
    render_answer_buttons,
    render_keyboard_hint,
    render_score_summary_cards,
    render_answer_review_list,
)

JOURNEY_TEST_QUESTIONS = 5  # Questions per 'full' stop mini-test

# ============================================================================
# HELPERS — queue navigation
# ============================================================================

def _current_stop(default_id=None):
    """Return the current queue stop dict, or a fallback."""
    queue = st.session_state.get('mastery_journey_queue', [])
    idx = st.session_state.get('mastery_journey_idx', 0)
    if queue and idx < len(queue):
        return queue[idx]
    return {'id': default_id, 'mode': 'full'}


def _is_last_stop():
    """Return True if the current stop is the final one in the queue."""
    queue = st.session_state.get('mastery_journey_queue', [])
    idx = st.session_state.get('mastery_journey_idx', 0)
    return idx >= len(queue) - 1


def _remaining_stops():
    """Return the number of stops still ahead of the current index."""
    queue = st.session_state.get('mastery_journey_queue', [])
    idx = st.session_state.get('mastery_journey_idx', 0)
    return len(queue) - idx - 1

def _render_journey_banner(tutor):
    """
    Render the journey-wide progress bar and stop counter.

    Hue shifts red→green as stops are completed.
    Displayed at the top of every MASTERY_JOURNEY_CARD screen.
    """
    queue = st.session_state.get('mastery_journey_queue', [])
    idx = st.session_state.get('mastery_journey_idx', 0)
    total = len(queue)
    pct = idx / total if total > 0 else 0
    hue = int(pct * 120)

    st.markdown(
        f"""
        <div style="margin-bottom: 8px;">
            <div class="progress-container">
                <div class="progress-fill" style="--bar-hue: {hue}; width: {pct * 100:.1f}%;"></div>
            </div>
            <div style="text-align: center; font-size: 0.85em; color: gray; margin-top: 4px;">
                Mastery Journey — Stop {idx + 1} of {total}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================================
# MASTERY_JOURNEY_CARD
# ============================================================================

def render_mastery_journey_card(tutor):
    """
    Render the lesson card for the current journey stop.

    Reads from content cache. Falls back to lesson_source if no cached card exists.
    Action buttons: "Start Mini-Test" (primary) and "Skip to Next" (secondary).

    Args:
    tutor: SimpleTutor instance
    """
    if st.session_state.pop('_journey_reset_view', False):
        unique_key = time.time() 
        
        components.html(
            f"""
            <script>
                // Cache bust ID: {unique_key}
                var body = window.parent.document.querySelector('section[data-testid="stMain"]');
                if (body) {{
                    body.scrollTop = 0;
                }}
            </script>
            """,
            height=0
        )
    
    stop = _current_stop(tutor.current_id)

    _render_journey_banner(tutor)

    if not st.session_state.get('current_course_path'):
        st.error("No course loaded.")
        return

    course_filename = Path(st.session_state.current_course_path).name
    current_id = stop.get('id', tutor.current_id)
    tutor.current_id = current_id
    current = tutor.syllabus.get(current_id, {})

    # Resolve content and view preference before rendering buttons
    content = (
        st.session_state.content_cache
        .get(course_filename, {})
        .get(current_id)
    )
    raw_fallback = current.get('lesson_source', '')
    if "mastery_preferred_view" not in st.session_state:
        st.session_state.mastery_preferred_view = "generated"
    view = st.session_state.mastery_preferred_view

    # ── Header row: back | spacer | [regen] [switch] [preview] ──────────────
    col_back, _, col_actions = st.columns([1, 5, 4])

    with col_back:
        if st.button("", icon=":material/arrow_back:", help="Back",
                     key="mastery_journey_card_back", use_container_width=True):
            terminate_mastery_batch(tutor)

    with col_actions:
        b_regen, b_switch, b_preview, b_media = st.columns(4)
        with b_regen:
            if st.button("", icon=":material/auto_awesome:", help="Regenerate content",
                         key="mastery_j_regen", use_container_width=True):
                st.session_state.mastery_preferred_view = "generated"
                st.session_state._journey_regenerating = True
                st.rerun()
        with b_switch:
            if st.button("", icon=":material/switch_access:",
                         help="Switch between generated lesson and raw source",
                         key="mastery_j_switch", use_container_width=True):
                st.session_state.mastery_preferred_view = "raw" if view == "generated" else "generated"
                st.rerun()
        with b_preview:
            peek_label   = "Source material"  if view == "generated" else "Generated lesson"
            peek_content = raw_fallback        if view == "generated" else content
            with st.popover("", icon=":material/description:",
                            help="Preview opposite view", use_container_width=True):
                st.caption(peek_label)
                if peek_content:
                    st.markdown(peek_content)
                else:
                    st.caption("No content available.")
                _media_render(course_filename, current_id, key_prefix="popover")
        with b_media:
            with st.popover("", icon=":material/attach_file:",
                            help="Add media attachment", use_container_width=True):
                _media_add_popover(course_filename, current_id)

    render_lesson_title(current.get('lesson_title', current_id))

    # ── Content area ─────────────────────────────────────────────────────────
    if st.session_state.get('_journey_regenerating'):
        st.session_state._journey_regenerating = False
        generated = _generate_lesson_content()
        if generated:
            st.rerun()
        # On failure: _generate_lesson_content() shows a warning inside the
        # lesson window — don't rerun so the message stays visible.
    elif view == "generated" and content:
        _display_lesson_content(content)
    elif view == "generated" and not content:
        if raw_fallback:
            st.info(
                "No cached card found for this lesson. "
                "Below is the raw data. Hit **Regenerate** to see the full LLM presentation."
            )
            with st.container(border=False, key="lesson_window"):
                st.markdown(raw_fallback)
                _media_render(course_filename, current_id)
        else:
            st.warning("No content available for this lesson.")
    else:
        # view == "raw"
        if raw_fallback:
            with st.container(border=False, key="lesson_window"):
                st.markdown(raw_fallback)
                _media_render(course_filename, current_id)
        else:
            st.info("No source material available.")

    _render_card_action_buttons(tutor, course_filename, current_id)
    


def _render_card_action_buttons(tutor, course_filename, current_id):
    """Render the bottom action buttons: [Start Mini-Test] and [Skip to Next]."""
    
    col_main, col_skip = st.columns([0.6, 0.4])
    
    with col_main:
        if st.button(
            "Start Mini-Test",
            icon=":material/quiz:",
            type="primary",
            use_container_width=True,
            key="journey_card_ready"
        ):
            _start_journey_mini_test(tutor, course_filename, current_id)
        render_keyboard_hint('start_mini_test')

        
            
    with col_skip:
        if st.button(
            "Skip to Next",
            icon=":material/skip_next:",
            type="secondary",
            use_container_width=True,
            key="journey_full_skip"
        ):
            _advance_journey(tutor)
        render_keyboard_hint('skip')


def _start_journey_mini_test(tutor, course_filename, element_id):
    """
    Load questions for journey mini-test and enter MASTERY_JOURNEY_TEST.
    Samples JOURNEY_TEST_QUESTIONS from the existing pool — no new generation.
    """
    pool = get_pool(course_filename, element_id)

    if not pool:
        st.error(
            "No question pool found for this lesson. "
            "Skip this stop or return to the course and complete it normally."
        )
        return

    sampled = sample_from_pool(pool, JOURNEY_TEST_QUESTIONS)

    st.session_state.questions = sampled
    st.session_state.answers = [None] * len(sampled)
    st.session_state.current_question_idx = 0
    st.session_state.is_quick_test = True

    tutor.state = 'MASTERY_JOURNEY_TEST'
    st.rerun()


# ============================================================================
# MASTERY_JOURNEY_TEST
# ============================================================================

def render_mastery_journey_test(tutor):
    """
    Render the 1-question mini-test for the current journey stop.

    Guards:
        - No questions loaded → error + redirect to MASTERY_JOURNEY_CARD
        - idx >= total_q     → hand off to _handle_journey_test_complete

    Args:
        tutor: SimpleTutor instance
    """
    
    stop = _current_stop(tutor.current_id)
    current_id = stop.get('id', tutor.current_id)
    tutor.current_id = current_id
    current = tutor.syllabus.get(current_id, {})

    source = current.get("lesson_source", "")

    def _delete_q():
        course_name = Path(st.session_state.get("current_course_path", "")).name
        qs  = st.session_state.get("questions") or []
        i   = st.session_state.get("current_question_idx", 0)
        q   = qs[i] if i < len(qs) else None
        if q:
            remove_question_from_pool(course_name, current_id, q)
            qs.pop(i)
            st.session_state.questions = qs
            if qs:
                st.session_state.current_question_idx = min(i, len(qs) - 1)
                st.session_state.answers = st.session_state.answers[:len(qs)]
            else:
                tutor.state = "MASTERY_JOURNEY_CARD"
        st.rerun()

    _course_filename = Path(st.session_state.get("current_course_path", "")).name
    if render_test_header(current.get("lesson_title", current_id), source, "mastery_journey_test", on_delete=_delete_q,
                          course_filename=_course_filename, lesson_id=current_id):
        terminate_mastery_batch(tutor)

    questions = st.session_state.get('questions', [])
    answers = st.session_state.get('answers', [])
    idx = st.session_state.get('current_question_idx', 0)
    total_q = len(questions)

    if not questions:
        st.error("No questions loaded. Returning to card.")
        tutor.state = 'MASTERY_JOURNEY_CARD'
        st.rerun()
        return

    if idx >= total_q:
        _handle_journey_test_complete(tutor, questions, answers)
        return

    q = questions[idx]

    render_test_progress_bar(idx, total_q)
    
    queue = st.session_state.get('mastery_journey_queue', [])
    journey_idx = st.session_state.get('mastery_journey_idx', 0)
    st.caption(f"Mastery Journey — Stop {journey_idx + 1} of {len(queue)}")

    render_question(q)
    render_answer_options(q)

    render_answer_buttons(idx, total_q)
    render_keyboard_hint('answers')

def _handle_journey_test_complete(tutor, questions, answers):
    """
    Render the mini-test result and route based on pass/fail.

    Pass (≥80%):
        Last stop  → "Complete Journey" → MASTERY_JOURNEY_DONE
        More ahead → "Continue Journey  •  N stops left" → _advance_journey

    Fail (<80%):
        "RETAKE TEST"     → re-samples pool, stays in MASTERY_JOURNEY_TEST
        "GO BACK TO CARD" → full_reset + MASTERY_JOURNEY_CARD
    """
    correct = sum(
        1 for q, ans in zip(questions, answers)
        if ans and ans.upper() == (q.get('correct') or q.get('answer', '')).upper()
    )
    total = len(questions)
    pct = correct / total * 100 if total else 0
    passed = pct >= 80

    # === SUMMARY CARDS ===
    render_score_summary_cards(correct, total, pct)
    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    # === ACTION BUTTONS ===
    if passed:
        if _is_last_stop():
            if st.button(
                "Complete Journey",
                icon=":material/done_all:",
                type="primary",
                use_container_width=True,
                key="journey_complete_btn"
            ):
                _finish_journey(tutor)
        else:
            remaining = _remaining_stops()
            stop_text = "stop" if remaining == 1 else "stops"
            
            if st.button(
                f"Continue Journey  •  {remaining} {stop_text} left",
                icon=":material/arrow_forward:",
                type="primary",
                use_container_width=True,
                key="journey_next_btn"
            ):
                _advance_journey(tutor)

        render_keyboard_hint('continue')

    else:
        col_retry, col_card = st.columns(2)
        with col_retry:
            if st.button(
                "Retake Test",
                icon=":material/replay:",
                type="secondary",
                use_container_width=True,
                key="journey_retry_btn"
            ):
                full_reset()
                # Re-sample from pool for a fresh attempt
                course_filename = Path(st.session_state.current_course_path).name
                pool = get_pool(course_filename, tutor.current_id)
                if pool:
                    sampled = sample_from_pool(pool, JOURNEY_TEST_QUESTIONS)
                    st.session_state.questions = sampled
                    st.session_state.answers = [None] * len(sampled)
                    st.session_state.current_question_idx = 0
                    st.session_state.is_quick_test = True
                tutor.state = 'MASTERY_JOURNEY_TEST'
                st.rerun()
            render_keyboard_hint('retake')

        with col_card:
            if st.button(
                "Go Back to Card",
                icon=":material/menu_book:",
                type="primary",
                use_container_width=True,
                key="journey_reread_btn"
            ):
                full_reset()
                tutor.state = 'MASTERY_JOURNEY_CARD'
                st.rerun()
            render_keyboard_hint('backspace')

    st.divider()

    # === DETAILED ANALYSIS ===
    render_answer_review_list(questions, answers, syllabus=st.session_state.tutor.syllabus)
    
# ============================================================================
# MASTERY COMPLETION
# ============================================================================

def render_mastery_journey_done(tutor):
    """
    Render the journey completion screen with stats and exit actions.

    Branches on journey origin:
        journey_return_to set  → "Retake: {label}" → back to checkpoint/final test
        journey_return_to None → "Run Another Test" + "Return to Course"

    Args:
        tutor: SimpleTutor instance
    """

    st.balloons()
    st.session_state['_journey_balloons_shown'] = True
    
    st.markdown(
        "### :material/verified: Mastery Journey Complete!\n"
        "**Incredible work!** You've successfully revisited the concepts you struggled with "
        "and turned those knowledge gaps into solid understanding. You are now fully prepared "
        "to return to your course and keep building momentum."
    )

    st.markdown("<hr style='margin-top: 1em; margin-bottom: 1.5em; opacity: 0.3;'>", unsafe_allow_html=True)

    queue = st.session_state.get('mastery_journey_queue', [])
    questions = st.session_state.get('mastery_questions', [])
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Lessons Revisited", len(queue))
    with c2:
        st.metric("Questions Answered", len(questions))
        

    st.markdown("<br>", unsafe_allow_html=True)
    return_to = st.session_state.get('journey_return_to')

    if return_to and return_to in tutor.syllabus:
        # Came from checkpoint/synthesis/final_test — one action only
        elem = tutor.syllabus[return_to]
        label = elem.get('lesson_title', 'Test')
        if st.button(
            f"Retake: {label}",
            icon=":material/military_tech:",
            type="primary",
            use_container_width=True,
            key="journey_retake_checkpoint"
        ):
            st.session_state.journey_return_to = None
            st.session_state.mastery_journey_active = False
            st.session_state.mastery_journey_queue = []
            st.session_state.mastery_journey_idx = 0
            tutor.current_id = return_to
            st.session_state.force_test = True   # skip the summary card
            full_reset()
            tutor.state = 'CARD'
            save_full_state()
            st.rerun()
        render_keyboard_hint('retake')

    else:
        # Came from normal mastery mode — original two-button layout
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button(
                "Take Another Test",
                icon=":material/refresh:",
                type="primary",
                use_container_width=True,
                key="journey_done_mastery"
            ):
                _exit_to_mastery_setup(tutor)
            render_keyboard_hint('continue')
        with col_b:
            if st.button(
                "Return to Course",
                icon=":material/school:",
                use_container_width=True,
                key="journey_done_course"
            ):
                _exit_to_course(tutor)
            render_keyboard_hint('backspace')

# ============================================================================
# NAVIGATION & EXIT
# ============================================================================

def _advance_journey(tutor):
    """
    Move to the next stop in the journey queue.
    If queue is exhausted, enter MASTERY_JOURNEY_DONE.
    """
    queue = st.session_state.get('mastery_journey_queue', [])
    idx = st.session_state.get('mastery_journey_idx', 0)
    next_idx = idx + 1

    if next_idx >= len(queue):
        _finish_journey(tutor)
        return

    st.session_state.mastery_journey_idx = next_idx
    next_stop = queue[next_idx]
    tutor.current_id = next_stop['id']
    tutor.state = 'MASTERY_JOURNEY_CARD'

    full_reset()
    save_full_state()
    st.session_state['_journey_reset_view'] = True
    st.rerun()

def _finish_journey(tutor):
    """Mark journey complete and enter MASTERY_JOURNEY_DONE."""
    st.session_state.mastery_journey_active = False
    tutor.state = 'MASTERY_JOURNEY_DONE'
    full_reset()
    st.rerun()

def _exit_to_mastery_setup(tutor):
    """Clean exit back to Mastery Mode setup."""
    st.session_state.mastery_journey_queue = []
    st.session_state.mastery_journey_idx = 0
    st.session_state.mastery_selected = {}
    st.session_state.mastery_questions = []
    st.session_state.pop('_journey_balloons_shown', None)
    full_reset()
    tutor.state = 'MASTERY_SETUP'
    st.rerun()

def _exit_to_course(tutor):
    """Clean exit back to normal course flow."""
    st.session_state.mastery_journey_queue = []
    st.session_state.mastery_journey_idx = 0
    st.session_state.mastery_journey_active = False
    st.session_state.mastery_questions = []
    st.session_state.mastery_selected = {}
    st.session_state.pop('_journey_balloons_shown', None)
    full_reset()
    tutor.state = 'CARD'
    save_full_state()
    st.rerun()