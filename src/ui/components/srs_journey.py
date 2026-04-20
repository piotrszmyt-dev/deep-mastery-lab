"""
SRS Journey
===========
Cross-course remediation loop after a failed SRS batch.

For each wrong-answer lesson, the journey shows:
  1. SRS_JOURNEY_CARD  — lesson card (AI-generated or lesson_source fallback)
                          buttons: [Start Mini-Test] [Skip to Next]
  2. SRS_JOURNEY_TEST  — 1-question mini-test sampled from the lesson pool
                          pass → advance to next stop (or SRS_JOURNEY_DONE)
                          fail → [Retake] [Go Back to Card]
  3. SRS_JOURNEY_DONE  — completion screen
                          buttons: [Start Next Batch] or [Back to SRS]

Mini-test results do NOT update FSRS scheduling — the journey is a
custom-study refresher only. FSRS is updated in srs_feedback.py.

Session state keys:
  srs_journey_queue  — list of {course_name, lesson_id} stops (set by srs_feedback.py)
  srs_journey_idx    — current stop index
"""

import streamlit as st
import streamlit.components.v1 as components
import random
import time
from src.managers.state_manager import full_reset
from src.managers import srs_manager
from src.managers.srs_manager import delete_card
from src.managers.cache_manager import remove_question_from_pool
from src.managers.models_manager import resolve_model_id
from src.managers.prefetch_manager import save_card_to_disk
from src.core.generators import generate_card_content
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
    render_lesson_window,
)
from src.ui.components.media_render import _media_render, _media_add_popover

JOURNEY_TEST_QUESTIONS = 5


# ============================================================================
# HELPERS — queue navigation
# ============================================================================

def _current_stop() -> dict:
    queue = st.session_state.get("srs_journey_queue", [])
    idx   = st.session_state.get("srs_journey_idx", 0)
    return queue[idx] if queue and idx < len(queue) else {}


def _is_last_stop() -> bool:
    queue = st.session_state.get("srs_journey_queue", [])
    idx   = st.session_state.get("srs_journey_idx", 0)
    return idx >= len(queue) - 1


def _remaining_stops() -> int:
    queue = st.session_state.get("srs_journey_queue", [])
    idx   = st.session_state.get("srs_journey_idx", 0)
    return len(queue) - idx - 1


def _render_journey_banner():
    queue = st.session_state.get("srs_journey_queue", [])
    idx   = st.session_state.get("srs_journey_idx", 0)
    total = len(queue)
    pct   = idx / total if total > 0 else 0
    hue   = int(pct * 120)

    st.markdown(
        f"""
        <div style="margin-bottom: 8px;">
            <div class="progress-container">
                <div class="progress-fill" style="--bar-hue: {hue}; width: {pct * 100:.1f}%;"></div>
            </div>
            <div style="text-align: center; font-size: 0.85em; color: gray; margin-top: 4px;">
                SRS Journey — Stop {idx + 1} of {total}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================================
# SRS_JOURNEY_CARD
# ============================================================================

def _get_preferred_view() -> str:
    """Return 'generated' or 'raw' from srs_settings. Defaults to 'generated'."""
    settings = srs_manager.load_settings()
    return settings.get("preferred_view", "generated")


def _save_preferred_view(mode: str) -> None:
    """Persist 'generated' or 'raw' to srs_settings.json."""
    settings = srs_manager.load_settings()
    settings["preferred_view"] = mode
    srs_manager.save_settings(settings)
    st.session_state.srs_preferred_view = mode


def render_srs_journey_card(srs_tutor):
    """Render the lesson card for the current journey stop."""
    if st.session_state.pop("_srs_journey_reset_view", False):
        uid = time.time()
        components.html(
            f"""<script>
            // {uid}
            var body = window.parent.document.querySelector('section[data-testid="stMain"]');
            if (body) body.scrollTop = 0;
            </script>""",
            height=0,
        )

    stop        = _current_stop()
    course_name = stop.get("course_name", "")
    lesson_id   = stop.get("lesson_id", "")
    lesson      = srs_tutor.get_lesson(course_name, lesson_id)

    # Resolve preferred view (session cache → disk)
    if "srs_preferred_view" not in st.session_state:
        st.session_state.srs_preferred_view = _get_preferred_view()
    view = st.session_state.srs_preferred_view  # "generated" or "raw"

    generated_content = srs_tutor.get_card_content(course_name, lesson_id)
    raw_content       = lesson.get("lesson_source", "")
    has_generated     = bool(generated_content)

    _render_journey_banner()

    # ── Header row: back | spacer | [regen] [switch] [preview] ───────────────
    col_back, _, col_actions = st.columns([1, 5, 4])

    with col_back:
        if st.button("", icon=":material/arrow_back:", help="Back",
                     key="srs_journey_card_back", use_container_width=True):
            _exit_journey_to_home()

    with col_actions:
        b_regen, b_switch, b_preview, b_media = st.columns(4)

        with b_regen:
            if st.button(
                "",
                icon=":material/auto_awesome:",
                help="Regenerate AI lesson card",
                key="srs_regen_card",
                use_container_width=True,
            ):
                adapter  = st.session_state.get("api_adapter")
                model_id = resolve_model_id(
                    st.session_state.get("active_provider"),
                    st.session_state.get("selected_models", {}).get("presentation", ""),
                )
                if not adapter:
                    st.error("No API adapter configured. Go to Settings → API.")
                else:
                    srs_tutor.get_lesson(course_name, lesson_id)
                    syllabus = srs_tutor._syllabi.get(course_name, {})
                    content = None
                    try:
                        with st.spinner("Generating lesson card…"):
                            content = generate_card_content(
                                syllabus=syllabus,
                                element_id=lesson_id,
                                adapter=adapter,
                                model_id=model_id,
                                user_prompt=st.session_state.get("custom_prompts", {}).get("presentation", ""),
                                course_filename=course_name,
                            )
                    except Exception:
                        pass
                    if content:
                        save_card_to_disk(course_name, lesson_id, content)
                        st.rerun()
                    else:
                        st.error("Generation failed. Check your API key and try again.")

        with b_switch:
            if st.button(
                "",
                icon=":material/switch_access:",
                help="Switch between generated lesson and raw source",
                key="srs_view_switch",
                use_container_width=True,
            ):
                new_view = "raw" if view == "generated" else "generated"
                _save_preferred_view(new_view)
                st.rerun()

        with b_preview:
            if view == "generated":
                peek_label   = "Source material"
                peek_content = raw_content
            else:
                peek_label   = "Generated lesson"
                peek_content = generated_content
            with st.popover(
                "",
                icon=":material/description:",
                help="Preview opposite view",
                use_container_width=True,
            ):
                st.caption(peek_label)
                if peek_content:
                    st.markdown(peek_content)
                else:
                    st.caption("No content available.")
                _media_render(course_name, lesson_id, key_prefix="popover")
        with b_media:
            with st.popover("", icon=":material/attach_file:",
                            help="Add media attachment", use_container_width=True):
                _media_add_popover(course_name, lesson_id)

    render_lesson_title(lesson.get("lesson_title", lesson_id))

    # ── Main content area ─────────────────────────────────────────────────────
    if view == "generated" and has_generated:
        with st.container(border=False, key="lesson_window"):
            st.markdown(generated_content, unsafe_allow_html=True)
            _media_render(course_name, lesson_id)
    elif view == "generated" and not has_generated:
        if raw_content:
            st.info(
                "No generated content — switch to source view or use **Regenerate** above "
                "to create an AI lesson card.",
                icon=":material/info:"
            )
            with st.container(border=False, key="lesson_window"):
                st.markdown(raw_content, unsafe_allow_html=True)
                _media_render(course_name, lesson_id)
        else:
            st.warning("No content available for this lesson.")
    else:
        # view == "raw"
        if raw_content:
            with st.container(border=False, key="lesson_window"):
                st.markdown(raw_content, unsafe_allow_html=True)
                _media_render(course_name, lesson_id)
        else:
            st.info("No source material available.")

    _render_card_action_buttons(srs_tutor, course_name, lesson_id)



def _render_card_action_buttons(srs_tutor, course_name: str, lesson_id: str):
    col_main, col_skip = st.columns([0.6, 0.4])
    with col_main:
        if st.button(
            "Start Mini-Test",
            icon=":material/quiz:",
            type="primary",
            use_container_width=True,
            key="srs_journey_start_test",
        ):
            _start_mini_test(srs_tutor, course_name, lesson_id)
        render_keyboard_hint("start_mini_test")

    with col_skip:
        if st.button(
            "Skip to Next",
            icon=":material/skip_next:",
            type="secondary",
            use_container_width=True,
            key="srs_journey_skip",
        ):
            _advance_journey(srs_tutor)
        render_keyboard_hint("skip")


def _start_mini_test(srs_tutor, course_name: str, lesson_id: str):
    pool = srs_tutor.get_question_pool(course_name, lesson_id)
    if not pool:
        st.error("No question pool for this lesson. Use Skip to continue.")
        return

    sampled = random.sample(pool, min(JOURNEY_TEST_QUESTIONS, len(pool)))
    # Inject _srs_meta so delete callbacks can identify course/block for DB removal.
    # Questions from get_question_pool() come raw from disk — no _srs_meta attached.
    for q in sampled:
        if "_srs_meta" not in q:
            q["_srs_meta"] = {
                "course_name": course_name,
                "block_id":    q.get("target_id", ""),
                "lesson_id":   lesson_id,
            }
    st.session_state.questions            = sampled
    st.session_state.answers              = [None] * len(sampled)
    st.session_state.current_question_idx = 0
    srs_tutor.state = "SRS_JOURNEY_TEST"
    st.rerun()


# ============================================================================
# SRS_JOURNEY_TEST
# ============================================================================

def render_srs_journey_test(srs_tutor):
    """Render the 1-question mini-test for the current journey stop."""
    stop        = _current_stop()
    course_name = stop.get("course_name", "")
    lesson_id   = stop.get("lesson_id", "")
    lesson      = srs_tutor.get_lesson(course_name, lesson_id)
    title       = lesson.get("lesson_title", lesson_id)
    source      = lesson.get("lesson_source", "")

    questions = st.session_state.get("questions") or []
    answers   = st.session_state.get("answers") or []
    idx       = st.session_state.get("current_question_idx", 0)
    total_q   = len(questions)

    if not questions:
        st.error("No questions loaded. Returning to card.")
        srs_tutor.state = "SRS_JOURNEY_CARD"
        st.rerun()
        return

    if idx >= total_q:
        _handle_mini_test_complete(srs_tutor, questions, answers, course_name, lesson_id)
        return

    if render_test_header(title, source, "srs_journey_test",
                          on_delete=lambda: _delete_journey_question(srs_tutor),
                          course_filename=course_name, lesson_id=lesson_id):
        srs_tutor.state = "SRS_JOURNEY_CARD"
        st.rerun()

    render_test_progress_bar(idx, total_q)
    render_question(questions[idx])
    render_answer_options(questions[idx])
    render_answer_buttons(idx, total_q)
    render_keyboard_hint("answers")


def _delete_journey_question(srs_tutor):
    """Remove the current mini-test question from the pool and SRS DB, then skip it."""
    questions = st.session_state.get("questions") or []
    idx       = st.session_state.get("current_question_idx", 0)
    if not questions or idx >= len(questions):
        return
    q           = questions[idx]
    meta        = q.get("_srs_meta", {})
    course_name = meta.get("course_name", "")
    block_id    = meta.get("block_id", "")
    lesson_id   = meta.get("lesson_id", "")
    if course_name and block_id:
        delete_card(course_name, block_id)
        remove_question_from_pool(course_name, lesson_id, q)
    questions.pop(idx)
    st.session_state.questions = questions
    if questions:
        st.session_state.current_question_idx = min(idx, len(questions) - 1)
        st.session_state.answers = st.session_state.answers[:len(questions)]
    else:
        srs_tutor.state = "SRS_JOURNEY_CARD"
    st.rerun()


def _handle_mini_test_complete(srs_tutor, questions, answers, course_name, lesson_id):
    correct = sum(
        1 for q, a in zip(questions, answers)
        if a is not None and a.upper() == (q.get("correct") or "").upper()
    )
    total  = len(questions)
    pct    = correct / total * 100 if total else 0
    passed = pct >= 80

    render_score_summary_cards(correct, total, pct)
    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    if passed:
        if _is_last_stop():
            if st.button(
                "Complete Journey",
                icon=":material/done_all:",
                type="primary",
                use_container_width=True,
                key="srs_journey_complete",
            ):
                srs_tutor.state = "SRS_JOURNEY_DONE"
                full_reset()
                st.rerun()
        else:
            remaining  = _remaining_stops()
            stop_label = "stop" if remaining == 1 else "stops"
            if st.button(
                f"Continue Journey  •  {remaining} {stop_label} left",
                icon=":material/arrow_forward:",
                type="primary",
                use_container_width=True,
                key="srs_journey_next",
            ):
                _advance_journey(srs_tutor)
        render_keyboard_hint("continue")
    else:
        col_retry, col_card = st.columns(2)
        with col_retry:
            if st.button(
                "Retake Test",
                icon=":material/replay:",
                type="secondary",
                use_container_width=True,
                key="srs_journey_retry",
            ):
                pool    = srs_tutor.get_question_pool(course_name, lesson_id)
                sampled = random.sample(pool, min(JOURNEY_TEST_QUESTIONS, len(pool))) if pool else []
                for q in sampled:
                    if "_srs_meta" not in q:
                        q["_srs_meta"] = {
                            "course_name": course_name,
                            "block_id":    q.get("target_id", ""),
                            "lesson_id":   lesson_id,
                        }
                full_reset()
                st.session_state.questions            = sampled
                st.session_state.answers              = [None] * len(sampled)
                st.session_state.current_question_idx = 0
                srs_tutor.state = "SRS_JOURNEY_TEST"
                st.rerun()
            render_keyboard_hint("retake")

        with col_card:
            if st.button(
                "Go Back to Card",
                icon=":material/menu_book:",
                type="primary",
                use_container_width=True,
                key="srs_journey_reread",
            ):
                full_reset()
                srs_tutor.state = "SRS_JOURNEY_CARD"
                st.rerun()
            render_keyboard_hint("review")

    st.divider()

    syllabus = srs_tutor._syllabi.get(course_name, {})
    render_answer_review_list(questions, answers, syllabus=syllabus)


# ============================================================================
# SRS_JOURNEY_DONE
# ============================================================================

def render_srs_journey_done(srs_tutor):
    """Completion screen after all journey stops are finished."""
    col_back, _ = st.columns([3, 7])
    with col_back:
        if st.button("", icon=":material/arrow_back:", help="Back",
                     use_container_width=True, key="srs_journey_done_back"):
            _exit_journey_to_home()

    st.balloons()

    st.markdown(
        "### :material/verified: SRS Journey Complete!\n"
        "You've revisited the concepts you struggled with. "
        "Next time these cards come up, you'll be better prepared."
    )
    st.markdown(
        "<hr style='margin-top:1em; margin-bottom:1.5em; opacity:0.3;'>",
        unsafe_allow_html=True,
    )

    queue = st.session_state.get("srs_journey_queue", [])
    st.metric("Lessons Revisited", len(queue))
    st.markdown("<br>", unsafe_allow_html=True)

    if srs_tutor.has_next_batch():
        col_a, col_b = st.columns([7,3])
        with col_a:
            if st.button(
                f"Start Next Batch  [{srs_tutor.remaining_due}]",
                icon=":material/arrow_forward:",
                type="primary",
                use_container_width=True,
                key="srs_done_next_batch",
            ):
                _exit_journey_to_next_batch(srs_tutor)
            render_keyboard_hint("continue")
        with col_b:
            if st.button(
                "Back to SRS",
                icon=":material/home:",
                use_container_width=True,
                key="srs_done_home",
            ):
                _exit_journey_to_home()
    else:
        if st.button(
            "Finish Review",
            icon=":material/done_all:",
            type="primary",
            use_container_width=True,
            key="srs_done_home",
        ):
            _exit_journey_to_home()
        render_keyboard_hint("continue")


# ============================================================================
# NAVIGATION
# ============================================================================

def _advance_journey(srs_tutor):
    queue    = st.session_state.get("srs_journey_queue", [])
    idx      = st.session_state.get("srs_journey_idx", 0)
    next_idx = idx + 1

    if next_idx >= len(queue):
        srs_tutor.state = "SRS_JOURNEY_DONE"
        full_reset()
        st.rerun()
        return

    st.session_state.srs_journey_idx           = next_idx
    st.session_state["_srs_journey_reset_view"] = True
    srs_tutor.state = "SRS_JOURNEY_CARD"
    full_reset()
    st.rerun()


def _exit_journey_to_next_batch(srs_tutor):
    st.session_state.srs_journey_queue = []
    st.session_state.srs_journey_idx   = 0
    srs_tutor.start_next_batch()
    full_reset()
    srs_tutor.load_batch_into_session(st.session_state)
    st.rerun()


def _exit_journey_to_home():
    st.session_state.srs_journey_queue = []
    st.session_state.srs_journey_idx   = 0
    st.session_state.srs_tutor         = None
    st.session_state.srs_app_open      = False
    st.session_state.tutor             = None
    full_reset()
    st.rerun()
