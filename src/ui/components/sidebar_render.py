"""
Sidebar Renderer
================
Complete rendering logic for the application sidebar.

This module handles:
- Application title and branding
- Settings/Course toggle button
- Mastery Mode button
- Progress bar display
- Course tree navigation with modules and lessons
- Quick test buttons
"""

import streamlit as st

from pathlib import Path

from src.utils.settings_utils import save_all_settings
from src.managers.state_manager import save_full_state, full_reset
from src.managers.cache_manager import get_pool, get_questions_for_range, get_questions_for_test, _reshuffle_options
from src.core.generators import generate_questions_background, get_raw_context_data
from src.managers.models_manager import resolve_model_id
from src.managers.srs_manager import get_due_count
from src.managers import srs_manager
from src.core.srs_tutor import SrsTutor
from src.managers.srs_manager import get_due_cards

_MASTERY_STATES = frozenset({
    'MASTERY_SETUP', 'MASTERY_TEST', 'MASTERY_FEEDBACK',
    'MASTERY_JOURNEY_CARD', 'MASTERY_JOURNEY_TEST', 'MASTERY_JOURNEY_DONE'
})

# =============================================================================
# Entry Point
# =============================================================================

def render_sidebar(tutor=None):
    """
    Render the complete application sidebar.

    The sidebar contains:
    1. App title and icon
    2. Hub toggle button (settings + learning modes when open)
    3. Progress bar (when course loaded)
    4. Course tree with modules and lessons

    Args:
        tutor: SimpleTutor instance (None when no course loaded)
    """
    with st.sidebar:

        # Title
        _render_title()

        # Hub Toggle
        _render_settings_toggle(tutor)
        st.markdown("<br>", unsafe_allow_html=True)


        # Course Tree (if not in hub view and course loaded)
        if not st.session_state.show_settings and tutor:
            _render_course_tree(tutor)

# =============================================================================
# Top-level sidebar sections
# =============================================================================

def _render_title():
    """Render the application title with icon."""
    st.markdown(
        '<h1 class="sidebar-title"><span class="material-icons">school</span> Deep Mastery Lab</h1>', 
        unsafe_allow_html=True
    )


def _render_settings_toggle(tutor=None):
    """Render the hub toggle button plus learning mode shortcuts when open."""
    if st.session_state.show_settings:
        if st.button(
            "Save & Return to Lab",
            icon=":material/assignment_return:",
            use_container_width=True,
            type="primary"
        ):
            save_all_settings()
            st.toast("Settings saved.", icon=":material/check_circle:")
            st.session_state.show_settings = False
            st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        # ── SRS Review ────────────────────────────────────────────────────────
        due_count = get_due_count()
        review_label = f"Start Review [{due_count}]" if due_count else "No Review"
        if st.button(
            review_label,
            icon=":material/event_repeat:",
            use_container_width=True,
            type="secondary",
            disabled=due_count == 0 or st.session_state.get('is_cloud', False),
            key="sidebar_srs_btn",
        ):
            due_cards = get_due_cards()
            if due_cards:
                batch_size = srs_manager.load_settings().get("batch_size", 10)
                srs_tutor = SrsTutor(due_cards, batch_size=batch_size)
                full_reset()
                srs_tutor.load_batch_into_session(st.session_state)
                st.session_state.srs_tutor     = srs_tutor
                st.session_state.srs_app_open  = False
                st.session_state.show_settings = False
                st.rerun()
        st.markdown('\n')
        # ── Manage Decks ──────────────────────────────────────────────────────
        if st.button(
            "Manage Decks",
            icon=":material/style:",
            use_container_width=True,
            key="sidebar_manage_decks_btn",
            type="secondary",
            disabled=st.session_state.get('is_cloud', False),
        ):
            st.session_state.srs_app_open  = True
            st.session_state.show_settings = False
            st.rerun()

        # ── Custom Study (Mastery Mode) — only when a course is loaded ────────
        if tutor:
            is_in_mastery  = tutor.state in _MASTERY_STATES
            journey_active = st.session_state.get("mastery_journey_active", False)

            if is_in_mastery:
                mastery_label = "Exit Custom Study"
                mastery_icon  = ":material/logout:"
            elif journey_active:
                mastery_label = "Return to Journey"
                mastery_icon  = ":material/model_training:"
            else:
                mastery_label = "Custom Study"
                mastery_icon  = ":material/model_training:"

            if st.button(
                mastery_label,
                icon=mastery_icon,
                use_container_width=True,
                key="sidebar_mastery_btn",
            ):
                st.session_state.show_settings = False
                if is_in_mastery:
                    st.session_state.mastery_journey_active = False
                    st.session_state.mastery_journey_queue  = []
                    st.session_state.mastery_journey_idx    = 0
                    full_reset()
                    tutor.state = "CARD"
                    save_full_state()
                elif journey_active:
                    queue = st.session_state.get("mastery_journey_queue", [])
                    idx   = st.session_state.get("mastery_journey_idx", 0)
                    if queue and idx < len(queue):
                        tutor.current_id = queue[idx]
                    tutor.state = "MASTERY_JOURNEY_CARD"
                    full_reset()
                else:
                    tutor.state = "MASTERY_SETUP"
                    full_reset()
                st.rerun()

    else:
        if st.button(
            "Hub",
            icon=":material/hub:",
            use_container_width=True,
            type="primary"
        ):
            st.session_state.show_settings = True
            st.rerun()


# =============================================================================
# Course tree
# =============================================================================

def _render_course_tree(tutor):
    """
    Render the course navigation tree with progress bar.
    
    Displays:
    - Progress bar showing completion percentage
    - Expandable modules
    - Subtitle headers (disabled buttons)
    - Lesson buttons with navigation
    - Quick test buttons
    
    Args:
        tutor: SimpleTutor instance with course data
    """
    st.divider()
    
    # Progress Bar
    _render_progress_bar(tutor)
    
    # Build module structure
    modules = _build_module_structure(tutor)
    
    # Render each module
    for m_id, elements in modules.items():
        _render_module(tutor, m_id, elements)


def _render_progress_bar(tutor):
    """
    Render progress bar showing course completion.
    
    Args:
        tutor: SimpleTutor instance
    """
    total = len(tutor.syllabus)
    passed = len(st.session_state.passed_elements)
    percentage = passed / total if total > 0 else 0

    # Calculate hue: 0 (red) -> 120 (green)
    hue_value = int(percentage * 120)

    st.caption(f"Progress: {passed}/{total} ({percentage:.1%})")
    st.markdown(
        f"""
        <div class="progress-container">
            <div class="progress-fill" style="--bar-hue: {hue_value}; width: {percentage*100}%;"></div>
        </div>
        """,
        unsafe_allow_html=True
    )


def _build_module_structure(tutor):
    """
    Build dictionary of modules with their elements.
    
    Args:
        tutor: SimpleTutor instance
    
    Returns:
        dict: {module_id: [(element_id, element_data), ...]}
    """
    modules = {}
    for eid, data in tutor.syllabus.items():
        if eid == '_master_index':
            continue
        m_id = data.get('module_id', eid.split('-')[0])
        if m_id not in modules:
            modules[m_id] = []
        modules[m_id].append((eid, data))
    return modules


def _render_module(tutor, m_id, elements):
    """
    Render a single module with its lessons.
    
    Args:
        tutor: SimpleTutor instance
        m_id: Module ID
        elements: List of (element_id, element_data) tuples
    """
    # Module title and status
    m_title = elements[0][1].get('module_title', '')
    module_passed = all(eid in st.session_state.passed_elements for eid, _ in elements)
    m_icon = "❖"
    m_suffix = " ● " if module_passed else ""
    if m_id == 'FINAL_TEST' or elements[0][1].get('type') == 'final_test':
        m_label = f"{m_icon} Final Test{m_suffix}"
    else:
        m_label = f"{m_icon} {m_id}: {m_title}{m_suffix}"
    
    # Check if current lesson is in this module
    is_expanded = any(eid == tutor.current_id for eid, _ in elements)
    
    with st.expander(m_label, expanded=is_expanded):
        last_c_title = None
        for eid, data in elements:
            _render_lesson_item(tutor, eid, data, last_c_title)
            last_c_title = data.get('module_subtitle')


def _render_lesson_item(tutor, eid, data, last_c_title):
    """
    Render a single lesson item (header or button).
    
    Args:
        tutor: SimpleTutor instance
        eid: Element ID
        data: Element data dict
        last_c_title: Previous subtitle (for header detection)
    """
    this_c_title = data.get('module_subtitle')
    
    # Render concept header if new concept
    if this_c_title and this_c_title != last_c_title:
        st.button(
            this_c_title,
            key=f"header_{eid}",
            disabled=True,
            type="tertiary",
            use_container_width=True
        )
    
    # Render lesson button
    _render_lesson_button(tutor, eid, data)


def _render_lesson_button(tutor, eid, data):
    """
    Render lesson navigation button with quick test option.
    
    Args:
        tutor: SimpleTutor instance
        eid: Element ID
        data: Element data dict
    """
    # Prepare display title
    display_title = data.get('lesson_title', '')
    elem_type = data.get('type', '')
    
    if elem_type == 'module_checkpoint':
        display_title = "**❖** Checkpoint"
    elif elem_type == 'module_synthesis':
        # Add separator before module summary
        st.markdown("<br>", unsafe_allow_html=True)
        display_title = "     **❖ Module Summary**"
    elif elem_type == 'final_test': 
        display_title = "The Journey Ends Here"
    
    # Status indicators
    is_ignored = eid in st.session_state.get('ignored_elements', set())
    is_passed = eid in st.session_state.passed_elements
    is_current = eid == tutor.current_id
    
    # Icon selection
    if is_ignored:
        icon = ":material/cancel:"
    elif is_current:
        icon = ":material/center_focus_strong:"
    elif is_passed:
        icon = ":material/check_circle:"
    else:
        icon = ":material/radio_button_unchecked:"
    
    label = f"{icon} {display_title}"
    
    # Different key for active vs inactive
    nav_key = f"nav_active_{eid}" if is_current else f"nav_bt_{eid}"
    
    # Two columns: Navigation button + Quick test button
    c_nav, c_test = st.columns([0.85, 0.15])
    
    with c_nav:
        if st.button(
            label,
            key=nav_key,
            type="tertiary",
            use_container_width=True
        ):
            _handle_lesson_navigation(tutor, eid)
    
    with c_test:
        if st.button(
            "⧉",
            key=f"q_{eid}",
            help="Quick Test",
            type="tertiary"
        ):
            _handle_quick_test(tutor, eid, st.session_state.api_adapter)

# =============================================================================
# Event Handlers
# =============================================================================

def _handle_lesson_navigation(tutor, eid):
    """
    Handle navigation to a specific lesson.
    
    Args:
        tutor: SimpleTutor instance
        eid: Element ID to navigate to
    """
    # Exit mastery states if navigating away
    if tutor.state in _MASTERY_STATES:
        st.session_state.mastery_journey_active = False

    tutor.current_id = eid
    tutor.state = 'CARD'
    save_full_state()
    full_reset()
    st.rerun()


def _handle_quick_test(tutor, eid, adapter):
    """
    Handle quick test launch for a given element.

    Dispatches to one of three paths:
    - module_checkpoint / module_synthesis: draws from children pools,
      respects test_counts settings, routes through normal FEEDBACK
      (mastery journey triggers on failure as usual)
    - lesson with existing pool: loads ALL questions — full pool, no cap
    - lesson with no pool: generates on demand, then loads full pool

    Quick tests skip SRS recording (is_quick_test=True) but otherwise
    route through the normal TEST → FEEDBACK flow.

    Args:
        tutor: SimpleTutor instance
        eid: Element ID to test
    """
    course_filename = Path(st.session_state.current_course_path).name \
        if st.session_state.current_course_path else None

    elem_data = tutor.syllabus.get(eid, {})
    elem_type = elem_data.get('type', 'lesson')

    def _start_test(questions):
        tutor.current_id = eid
        tutor.state = 'TEST'
        full_reset()
        st.session_state.questions = questions
        st.session_state.answers = [None] * len(questions)
        st.session_state.current_question_idx = 0
        st.session_state.is_quick_test = True
        st.rerun()

    # PATH A: Checkpoint / Synthesis — draw from children pools using settings count
    if elem_type in ('module_checkpoint', 'module_synthesis'):
        children_ids = elem_data.get('children_ids', [])
        test_cnt = st.session_state.test_counts.get(elem_type, 10)
        questions = get_questions_for_range(course_filename, children_ids, test_cnt)
        if not questions:
            st.toast("No questions available. Complete some lessons in this module first.", icon=":material/block:")
            return
        _start_test(questions)
        return

    # PATH B: Pool exists — load ALL questions (no cap, this is a personal refresh)
    existing_pool = get_pool(course_filename, eid) if course_filename else None
    if existing_pool:
        _start_test(_reshuffle_options(list(existing_pool)))
        return

    # PATH C: No pool — generate on demand, then load full pool
    if not elem_data.get('lesson_content'):
        st.toast("No content available to generate questions for this lesson.", icon=":material/block:")
        return

    with st.spinner("No questions for this lesson yet — generating on demand..."):
        model_id = resolve_model_id(
            st.session_state.active_provider,
            st.session_state.selected_models['questions']
        )
        prompt_instruction = st.session_state.custom_prompts['questions']
        raw_context = get_raw_context_data(
            tutor.syllabus, eid,
            st.session_state.get('lesson_context_window', 3)
        )

        _lc = elem_data.get('lesson_content', [])
        _pool_size = sum(b.get('questions', 0) for b in _lc) if isinstance(_lc, list) else None
        _block_id = elem_data.get('source_ids', ['UNKNOWN'])[0]

        def generate_pool():
            return generate_questions_background(
                raw_context, adapter,
                model_id, prompt_instruction, course_filename,
                _block_id,
                count=_pool_size or None,
            )

        get_questions_for_test(course_filename, eid, st.session_state.get('lesson_max_questions', 0) or 999, generate_pool)
        questions = get_pool(course_filename, eid)

    if questions:
        _start_test(list(questions))
    else:
        st.toast("Failed to generate questions. Try again.", icon=":material/warning:")