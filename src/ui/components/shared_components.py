"""
Shared UI Components
====================
Reusable rendering primitives shared across learn and mastery flows.

Sections:
- Common:   progress bar, keyboard hints, lesson title
- Card:     lesson window container
- Test:     question display, answer options, answer buttons
- Feedback: score summary cards, answer review (correct/incorrect)
"""

import streamlit as st
from src.managers.state_manager import save_full_state, full_reset

# =============================================================================
# Common Helpers
# =============================================================================

def handle_skip(tutor):
    """Mark current as passed and skip to next."""
    st.session_state.passed_elements.add(tutor.current_id)
    tutor.move_to_next()
    save_full_state()
    full_reset()
    st.rerun()

# =============================================================================
# Common Renders
# =============================================================================

def render_lesson_title(title: str):
    """
    Render the lesson title heading inside the keyed title container.

    Preserves key="lesson_title" used by CSS for layout.

    Args:
        title: Lesson title string (without ❖ prefix)
    """
    with st.container(key="lesson_title"):
        st.markdown(f"### ❖ {title}")


def render_test_header(
    title: str,
    source: str,
    key_prefix: str,
    on_delete=None,
    on_edit=None,
    edit_question: dict = None,
    course_filename: str = None,
    lesson_id: str = None,
) -> bool:
    """
    Render the standard test header: back button | spacer | source popover [+ edit] [+ delete],
    then the lesson title below.

    Args:
        title:           Lesson title string.
        source:          Source material markdown text (empty string = show fallback caption).
        key_prefix:      Unique prefix for widget keys — must differ per render file.
        on_delete:       Optional callable. When provided, a delete button is shown and
                         on_delete() is called when confirmed.
        on_edit:         Optional callable(new_q_text, new_a_text). When provided, an edit
                         button is shown pre-filled with edit_question data.
        edit_question:   Question dict used to pre-fill the edit popover (required with on_edit).
        course_filename: Course filename for media rendering (e.g. "course.json").
        lesson_id:       Lesson element ID for media rendering (e.g. "L01").

    Returns:
        True if the back button was clicked.
    """
    from src.ui.components.media_render import _media_render

    n_action_cols = 1 + bool(on_edit) + bool(on_delete)
    col_back, _, col_actions = st.columns([1, 10 - n_action_cols, n_action_cols])
    back_clicked = False

    with col_back:
        back_clicked = st.button(
            "",
            icon=":material/arrow_back:",
            help="Back",
            use_container_width=True,
            key=f"{key_prefix}_back",
        )

    with col_actions:
        buttons = []
        if on_delete:
            buttons.append("delete")
        if on_edit:
            buttons.append("edit")
        buttons.append("source")

        cols = st.columns(len(buttons))
        for col, btn in zip(cols, buttons):
            with col:
                if btn == "source":
                    with st.popover("", icon=":material/tab:", help="Show source material",
                                    use_container_width=True):
                        if source:
                            st.markdown(source)
                        else:
                            st.caption("No source material available.")
                        if course_filename and lesson_id:
                            _media_render(course_filename, lesson_id, key_prefix="popover")

                elif btn == "edit":
                    _eq = edit_question or {}
                    _cl = _eq.get("correct", "A")
                    # Use target_id in widget keys so each question gets a fresh
                    # widget — fixed keys cause Streamlit to reuse cached state
                    # from the first question for the rest of the batch.
                    _tid = _eq.get("target_id", str(id(_eq)))
                    with st.popover("", icon=":material/edit:", help="Edit this question",
                                    use_container_width=True):
                        st.caption("Fix a wording issue or factual error in this question.")
                        st.caption("Only the question text and correct answer are editable. "
                                   "Distractors (B, C, D) and SRS scheduling are not affected.")
                        new_q = st.text_area(
                            "Question",
                            value=_eq.get("question", ""),
                            key=f"{key_prefix}_edit_q_{_tid}",
                        )
                        new_a = st.text_area(
                            "Correct answer",
                            value=_eq.get("options", {}).get(_cl, ""),
                            key=f"{key_prefix}_edit_a_{_tid}",
                        )
                        if st.button("Save", icon=":material/save:", type="primary",
                                     use_container_width=True,
                                     key=f"{key_prefix}_edit_confirm_{_tid}"):
                            on_edit(new_q, new_a)

                elif btn == "delete":
                    with st.popover("", icon=":material/delete:", help="Remove this question permanently",
                                    use_container_width=True,
                                    disabled=st.session_state.get('is_cloud', False)):
                        st.caption("Remove this question permanently? This cannot be undone.")
                        if st.button("Delete", icon=":material/delete_forever:", type="primary",
                                     use_container_width=True, key=f"{key_prefix}_del_confirm"):
                            on_delete()

    render_lesson_title(title)
    return back_clicked


def render_test_progress_bar(idx: int, total_q: int):
    """
    Render animated question progress bar with counter label.

    Hue shifts red→green as the test progresses.
    Used in TEST and MASTERY_JOURNEY_TEST.

    Args:
        idx: Current question index (0-based)
        total_q: Total number of questions
    """
    percentage = (idx + 1) / total_q
    hue_value = int(percentage * 120)

    st.markdown(
        f"""
        <div style="margin-bottom: 8px;">
            <div class="progress-container">
                <div class="progress-fill" style="--bar-hue: {hue_value}; width: {percentage * 100}%;"></div>
            </div>
            <div style="text-align: center; font-size: 0.85em; color: gray; margin-top: 4px;">
                Question {idx + 1} / {total_q}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_keyboard_hint(mode: str):
    """
    Render a keyboard shortcut legend below action buttons.

    Modes:
        'answers'         — "Use Keyboard: 1=A 2=B 3=C 4=D"   (test answer selection)
        'start_test'      — "Start Test: Enter ↵"             (card → test, centered)
        'start_mini_test' — "Press Enter ↵ to start test"     (journey card → mini-test)
        'continue'        — "Press Enter ↵ to continue"       (feedback pass, journey pass)
        'retry'           — "Press Enter ↵ to retry"          (feedback fail)
        'review'          — "Press Enter ↵ to review content" (journey fail)
        'begin_journey'   — "Press Enter ↵ to begin journey"  (journey fail)
    Args:
        mode: One of the mode strings listed above
    """
    if mode == 'answers':
        st.markdown(
            """
            <div class="keyboard-legend">
                Use Keyboard: 
                1 = <span class="key-hint">A</span>&nbsp;
                2 = <span class="key-hint">B</span>&nbsp;
                3 = <span class="key-hint">C</span>&nbsp;
                4 = <span class="key-hint">D</span>
            </div>
            """,
            unsafe_allow_html=True
        )

    elif mode == 'start_test':
        st.markdown(
            """
            <div class="keyboard-legend" style="
                justify-content: center;
                display: flex;
                align-items: center;
            ">
                Start Test: <span class="key-hint">Enter ↵</span>
            </div>
            """,
            unsafe_allow_html=True
        )

    elif mode == 'start_mini_test':
        st.markdown(
            """<div class="keyboard-legend">
                Press <span class="key-hint">Enter ↵</span> to start test
            </div>""",
            unsafe_allow_html=True
        )

    elif mode == 'continue':
        st.markdown(
            """<div class="keyboard-legend">
                Press <span class="key-hint">Enter ↵</span> to continue
            </div>""",
            unsafe_allow_html=True
        )

    elif mode == 'retry':
        st.markdown(
            """<div class="keyboard-legend">
                Press <span class="key-hint">Enter ↵</span> to retry
            </div>""",
            unsafe_allow_html=True
        )

    elif mode == 'review':
        st.markdown(
            """<div class="keyboard-legend">
                Press <span class="key-hint">Enter ↵</span> to review content
            </div>""",
            unsafe_allow_html=True
        )
    elif mode == 'begin_journey':
        st.markdown(
            """<div class="keyboard-legend">
                Press <span class="key-hint">Enter ↵</span> to begin journey
            </div>""",
            unsafe_allow_html=True
        )

    elif mode == 'begin_journey_j':
        st.markdown(
            """<div class="keyboard-legend">
                Press <span class="key-hint">J</span> to begin journey
            </div>""",
            unsafe_allow_html=True
        )

    elif mode == 'skip':
        st.markdown(
            """<div class="keyboard-legend">
                Press <span class="key-hint">S</span> to skip
            </div>""",
            unsafe_allow_html=True
        )

    elif mode == 'retake':
        st.markdown(
            """<div class="keyboard-legend">
                Press <span class="key-hint">R</span> to retake
            </div>""",
            unsafe_allow_html=True
        )

    elif mode == 'backspace':
        st.markdown(
            """<div class="keyboard-legend">
                Press <span class="key-hint">⌫ Backspace</span> to go back
            </div>""",
            unsafe_allow_html=True
        )

def render_mark_previous_button(tutor):
    """Render 'Manage Previous' menu with bulk actions."""
    all_ids = list(tutor.syllabus.keys())
    
    # 1. Calculate Logic
    try:
        curr_idx = all_ids.index(tutor.current_id)
        prev_count = curr_idx + 1  # include current lesson
    except ValueError:
        prev_count = 0

    prev_ids = all_ids[:curr_idx + 1]  # include current lesson
    passed_prev_count = sum(1 for pid in prev_ids if pid in st.session_state.passed_elements)
    
    # 2. Render Popover
    with st.popover(
        label="",  # Added label for clarity (optional, can be empty)
        icon=":material/skip_previous:", # Changed to history for better context
        help=f"Manage progress for {prev_count} previous lessons",
        disabled=(prev_count == 0),
        use_container_width=True
    ):
        # --- Header & Stats ---
        st.markdown("### Previous Progress")
        
        # Grid layout for stats
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Previous", prev_count, border=True)
        with col2:
            st.metric("Completed", passed_prev_count, border=True)
        
        st.caption("Bulk Actions")

        # --- Actions ---
        
        # Action 1: Mark All Complete
        # Use 'done_all' icon. Disable if progress is already 100%.
        if st.button(
            "Mark all as done",
            icon=":material/done_all:",
            type="primary",
            key="head_mark_prev",
            use_container_width=True,
            disabled=(passed_prev_count == prev_count) 
        ):
            st.session_state.passed_elements.update(prev_ids)
            st.toast(f"Success! All {prev_count} previous lessons marked complete.", icon=":material/check_circle:")
            save_full_state()
            st.rerun()
        
        # Action 2: Reset Progress
        # Use 'remove_done' or 'undo' icon. Disable if progress is 0%.
        if st.button(
            "Reset previous progress",
            icon=":material/remove_done:", 
            type="secondary",
            key="head_unmark_prev",
            use_container_width=True,
            disabled=(passed_prev_count == 0)
        ):
            st.session_state.passed_elements.difference_update(prev_ids)
            st.toast(f"Reset complete. {passed_prev_count} lessons marked as fresh.", icon=":material/refresh:")
            save_full_state()
            st.rerun()


# =============================================================================
# Card
# =============================================================================

def render_lesson_window(content: str, key: str = "lesson_window"):
    """
    Render lesson markdown content inside the keyed lesson window container.

    Preserves key="lesson_window" used by CSS for layout.

    Args:
        content: Markdown string to display
        key: Container key (default "lesson_window")
    """
    with st.container(border=False, key=key):
        st.markdown(content, unsafe_allow_html=True)


# =============================================================================
# Test
# =============================================================================

def render_question(q: dict):
    """
    Render the question text in a bordered container.

    Preserves key="question" used by CSS.

    Args:
        q: Question dict with at least a 'text' key
    """
    with st.container(border=True, key="question"):
        st.markdown(q.get('question', q.get('text', '')))


def render_answer_options(q: dict):
    """
    Render all four answer options (A–D) in individual bordered containers.

    Preserves keys "answer_0" … "answer_3" used by CSS.

    Args:
        q: Question dict with an 'options' list of four strings
    """
    for i, letter in enumerate(['A', 'B', 'C', 'D']):
        opts = q['options']
        option_text = opts[letter] if isinstance(opts, dict) else opts[i]
        with st.container(border=True, key=f"answer_{i}"):
            st.markdown(f"**[ {letter} ]** {option_text}")


def render_answer_buttons(idx: int, total_q: int, on_complete=None):
    """
    Render A/B/C/D answer selection buttons and handle selection.

    Used in three test flows, each passing its own on_complete callback
    to handle the state transition when the last question is answered:

        learn_test_render.py        → tutor.state = 'FEEDBACK'
        mastery_mode_test_render.py → tutor.state = 'MASTERY_FEEDBACK'
        mastery_journey_render.py   → tutor.state = 'MASTERY_JOURNEY_TEST'
                                      (idx >= total_q guard catches completion on rerun)

    If on_complete is None, sets current_question_idx = total_q and reruns —
    the caller's renderer is responsible for detecting idx >= total_q.

    Keys use the fixed pattern ans_{idx}_{letter} — only one test renders
    at a time so no collision is possible.

    Args:
        idx: Current question index (0-based)
        total_q: Total number of questions
        on_complete: Optional callable invoked when the last question is answered.
                     Receives no arguments. Captures tutor via closure in the caller.
    """
    col_a, col_b, col_c, col_d = st.columns(4)

    for col, letter in zip([col_a, col_b, col_c, col_d], ['A', 'B', 'C', 'D']):
        with col:
            if st.button(
                letter,
                key=f"ans_{idx}_{letter}",
                use_container_width=True,
                type="primary"
            ):
                st.session_state.answers[idx] = letter

                if idx < total_q - 1:
                    st.session_state.current_question_idx += 1
                elif on_complete:
                    on_complete()
                else:
                    st.session_state.current_question_idx = total_q

                st.rerun()


# =============================================================================
# Feedback
# =============================================================================

def render_score_summary_cards(
    correct: int,
    total: int,
    pct: float,
    mark_passed_id: str | None = None
):
    """
    Render the three score summary cards: Score / Accuracy / Status.

    Preserves CSS classes: feedback-box metric, metric-label, metric-value,
    status-passed, status-failed.

    Args:
        correct: Number of correct answers
        total: Total number of questions
        pct: Percentage score (0–100)
        mark_passed_id: If provided and pct >= 80, adds this element ID to
                        passed_elements. Pass tutor.current_id for learn flow,
                        None for mastery journey (journey manages its own state).
    """
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown(
            f"""
            <div class="feedback-box metric">
                <div class="metric-label">Score</div>
                <div class="metric-value">{correct} / {total}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with c2:
        st.markdown(
            f"""
            <div class="feedback-box metric">
                <div class="metric-label">Accuracy</div>
                <div class="metric-value">{pct:.0f}%</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with c3:
        if pct >= 80:
            if mark_passed_id:
                st.session_state.passed_elements.add(mark_passed_id)
            st.markdown(
                """
                <div class="feedback-box status status-passed">
                    <span class="material-icons">emoji_events</span>
                    MASTERY ACHIEVED
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                """
                <div class="feedback-box status status-failed">
                    <span class="material-icons">fact_check</span>
                    NEEDS REVIEW
                </div>
                """,
                unsafe_allow_html=True
            )


def render_answer_review_list(questions: list, answers: list, syllabus: dict = None):
    """
    Render the full detailed question-by-question review section.

    Preserves key="feedback_list" and expander structure.
    Wrong answers are expanded by default.
    Supports both 'correct' and 'answer' keys for cross-flow compatibility.

    Args:
        questions: List of question dicts
        answers: List of selected answer letters (A/B/C/D or None)
    """
    st.caption("DETAILED ANALYSIS")

    with st.container(key="feedback_list", border=False):
        for i, (q, a) in enumerate(zip(questions, answers)):
            correct_ans = q.get('correct') or q.get('answer', '')
            is_correct = a is not None and a.upper() == correct_ans.upper()
            icon_name = ":material/check_circle:" if is_correct else ":material/cancel:"

            with st.expander(
                f"Question {i + 1}",
                expanded=(not is_correct),
                icon=icon_name
            ):
                _render_question_review(q, a, is_correct, correct_ans, syllabus)

        st.markdown("<div style='height: 100px;'></div>", unsafe_allow_html=True)


def _render_question_review(q: dict, a: str | None, is_correct: bool, correct_ans: str, syllabus: dict = None):
    """
    Render a single question review block inside an expander.

    Args:
        q: Question dict
        a: User's answer letter or None
        is_correct: Whether the answer was correct
        correct_ans: The correct answer letter
        syllabus: Full syllabus dict for source paragraph lookup
    """
    st.markdown(f"**{q.get('question', q.get('text', ''))}**")

    options = q.get('options', {})

    # Support both dict (new) and list (legacy) options format
    if isinstance(options, dict):
        user_text    = options.get(a, 'No Answer') if a else 'No Answer'
        correct_text = options.get(correct_ans, '')
    else:
        letter_map   = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
        user_text    = options[letter_map[a]] if a in letter_map and letter_map[a] < len(options) else 'No Answer'
        correct_text = options[letter_map[correct_ans]] if correct_ans in letter_map and letter_map[correct_ans] < len(options) else ''

    if is_correct:
        render_correct_answer_card(a, user_text)
    else:
        render_incorrect_answer_card(a or '—', user_text, correct_ans, correct_text)

    # Source paragraphs insight — replaces AI explanation
    source_ids = q.get('source_ids', [])
    if source_ids and syllabus:
        # Prefer the per-course index to avoid PID collisions across courses
        # (all courses use sequential IDs P001, P002 … so a flat merge is wrong)
        _srs_course = q.get('_srs_meta', {}).get('course_name')
        _per_course = syllabus.get('_course_master_indexes', {})
        master_index = _per_course.get(_srs_course) if _srs_course and _per_course else None
        if master_index is None:
            master_index = syllabus.get('_master_index', {})
        seen = set()
        ordered = [s for s in source_ids if not (s in seen or seen.add(s))]
        texts = [master_index.get(pid, '').strip() for pid in ordered if master_index.get(pid, '').strip()]
        if texts:
            body = "\n>\n> ".join(texts)
            st.markdown(
                f"> <span class='material-icons insight-icon'>lightbulb</span> "
                f"<span class='insight-label'>SOURCE</span>\n>\n> {body}",
                unsafe_allow_html=True
            )

    # Media attachments — derive course_filename and lesson_id from question metadata
    from src.ui.components.media_render import _media_render
    meta = q.get('_srs_meta', {})
    _course = meta.get('course_name') or (
        __import__('pathlib').Path(st.session_state.get('current_course_path', '')).name
        if st.session_state.get('current_course_path') else None
    )
    _lesson = meta.get('lesson_id') or q.get('element_id')
    if not _lesson and source_ids:
        # Derive lesson_id from block_id: "P035" → look up element owning P035
        if syllabus:
            for eid, elem in syllabus.items():
                if isinstance(elem, dict) and source_ids[0] in elem.get('source_ids', []):
                    _lesson = eid
                    break
    if _course and _lesson:
        _media_render(_course, _lesson, key_prefix=f"feedback_{id(q)}")

def render_correct_answer_card(letter: str, text: str):
    """
    Render a green 'correct answer' card.

    Preserves CSS classes: comparison-container, answer-card user-correct,
    answer-label, nordic-green.

    Args:
        letter: Answer letter (A/B/C/D)
        text: Answer option text
    """
    st.markdown(
        f"""
        <div class="comparison-container">
            <div class="answer-card user-correct">
                <span class="answer-label" style="color:var(--nordic-green);">
                    <span class="material-icons" style="font-size:1.1em; vertical-align:text-bottom; margin-right:4px;">check_circle</span>
                    YOUR ANSWER ({letter})
                </span>
                {text}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_incorrect_answer_card(
    user_letter: str,
    user_text: str,
    correct_letter: str,
    correct_text: str
):
    """
    Render a red/green comparison card for an incorrect answer.

    Preserves CSS classes: comparison-container, answer-card user-wrong,
    answer-card correct-key, answer-label, nordic-red, nordic-green.

    Args:
        user_letter: User's selected letter (A/B/C/D or '—' if none)
        user_text: User's answer option text
        correct_letter: The correct answer letter
        correct_text: The correct answer option text
    """
    st.markdown(
        f"""
        <div class="comparison-container">
            <div class="answer-card user-wrong">
                <span class="answer-label" style="color:var(--nordic-red);">
                    <span class="material-icons" style="font-size:1.1em; vertical-align:text-bottom; margin-right:4px;">cancel</span>
                    YOUR ANSWER ({user_letter})
                </span>
                {user_text}
            </div>
            <div class="answer-card correct-key">
                <span class="answer-label" style="color:var(--nordic-green);">
                    <span class="material-icons" style="font-size:1.1em; vertical-align:text-bottom; margin-right:4px;">check_circle</span>
                    CORRECT ANSWER ({correct_letter})
                </span>
                {correct_text}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )