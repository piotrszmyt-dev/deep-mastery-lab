"""
Welcome Window Renderer
=======================
Complete rendering logic for the welcome/course selection screen.

This module handles:
- Welcome header with branding
- Course selection dropdown
- Progress visualization for selected course
- Action buttons (Initialize/Resume/API Settings)
- AI Course Creator launcher
- Fallback course file uploader
"""

import streamlit as st
import json
from pathlib import Path
from titlecase import titlecase

from src.utils.course_utils import get_available_courses
from src.managers.state_manager import load_course
from src.managers import srs_manager
from src.managers.srs_manager import get_due_count, get_due_cards
from src.core.srs_tutor import SrsTutor
from src.managers.state_manager import full_reset

def render_welcome_window():
    """
    Render the complete welcome/course selection window.
    
    This is shown when no course is loaded (st.session_state.tutor is None).
    
    Flow:
    1. Display welcome header
    2. Verify API key status
    3. Show course selection dropdown
    4. Display progress bar for selected course
    5. Show action buttons (Initialize/Resume/Calibration)
    6. Footer: AI Course Creator button + connection status
    7. Fallback file uploader if no courses available
    """
    api_key_valid = bool(st.session_state.get('api_adapter'))
    # Top spacer
    st.markdown("<br>", unsafe_allow_html=True)
    
    with st.container(border=False, key="welcome_card"):
        # 1. Header
        _render_header()
        
        # 2. Course Selection & Progress
        courses = get_available_courses()
        courses.sort()
        try:
            _hidden = set(st.session_state.settings_manager.load().get("hidden_courses", []))
            courses = [c for c in courses if c not in _hidden]
        except Exception:
            pass
        selected_option = _render_course_selection(courses)
        
        # 3. Progress Bar
        if selected_option:
            has_progress, ratio = _get_course_progress(selected_option)
            _render_progress_bar(ratio)
        else:
            has_progress = False
        
        # 4. Action Buttons + Tools
        if selected_option:
            _render_action_buttons(selected_option, has_progress, api_key_valid)
        elif not courses:
            _render_no_courses_fallback()

        # 5. Status
        if api_key_valid:
            st.caption("🟢 System Online")
        else:
            st.caption("🔴 System Offline — Go to **API Settings** to connect")

# =============================================================================
# PRIVATE RENDER HELPERS
# =============================================================================

def _render_header():
    """Render welcome header with title and subtitle."""
    st.markdown(
        """
        <div class="welcome-title">
            <span class="material-icons">school</span> 
            Deep Mastery Lab
        </div>
        <div class="welcome-subtitle">
            Initialize Learning Sequence
        </div>
        """, 
        unsafe_allow_html=True
    )

def _render_course_selection(courses):
    """
    Render course selection dropdown.
    
    Args:
        courses: List of available course filenames
    
    Returns:
        str: Selected course filename (or None)
    """
    if not courses:
        return None
    
    # Get default index from last active course
    default_index = 0
    last_course = st.session_state.get('last_active_course', '')
    if last_course and last_course in courses:
        default_index = courses.index(last_course)
    
    def _format_course(filename: str) -> str:
        try:
            overrides = st.session_state.settings_manager.load().get("course_display_names", {})
            return overrides.get(filename) or titlecase(Path(filename).stem.replace("_", " "))
        except Exception:
            return titlecase(Path(filename).stem.replace("_", " "))

    # Render selectbox
    selected_option = st.selectbox(
        "Select Curriculum:",
        courses,
        index=default_index,
        format_func=_format_course,
        label_visibility="visible"
    )
    
    return selected_option

def _get_course_progress(course_filename):
    """
    Get progress data for a course.
    
    Args:
        course_filename: Course file name
    
    Returns:
        tuple: (has_progress: bool, ratio: float)
    """
    has_progress = st.session_state.progress_manager.exists(course_filename)
    ratio = 0.0
    
    try:
        course_path = Path("data/courses") / course_filename
        with open(course_path, 'r', encoding='utf-8') as f:
            course_data = json.load(f)
            total = len(course_data)
        
        if has_progress:
            prog = st.session_state.progress_manager.load(course_filename)
            passed = len(prog.get('passed_elements', [])) if prog else 0
            ratio = passed / total if total > 0 else 0.0
    except:
        ratio = 0.0
    
    return has_progress, ratio


def _render_progress_bar(ratio):
    """
    Render progress bar with percentage.
    
    Args:
        ratio: Progress ratio (0.0 to 1.0)
    """
    hue_value = int(ratio * 120)
    st.markdown(
        f"""
        <div style="margin-top: -10px; margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-between; font-size: 0.8em; color: var(--nordic-silver); margin-bottom: 4px;">
                <span>MASTERY PROGRESS</span>
                <span>{ratio:.0%}</span>
            </div>
            <div class="progress-container">
                <div class="progress-fill" style="--bar-hue: {hue_value}; width: {ratio*100}%;"></div>
            </div>
        </div>
        """, 
        unsafe_allow_html=True
    )


def _render_action_buttons(selected_option, has_progress, api_key_valid):
    """
    Row 1: Resume/Initialize + Review
    Divider
    Row 2: AI Course Creator | Manage Decks | API Settings
    Status caption
    """
    due_count = get_due_count()

    # ── Row 1: Primary actions ────────────────────────────────────────────────
    c_course, c_review = st.columns([6,3])

    with c_course:
        btn_text = "Resume Learning" if has_progress else "Initialize Course"
        btn_icon = ":material/rocket_launch:" if has_progress else ":material/play_circle:"
        if st.button(btn_text, icon=btn_icon, type="primary", use_container_width=True):
            load_course(selected_option)
            st.rerun()

    with c_review:
        queue_label = f"Review [{due_count}]" if due_count else "No Review"
        if st.button(
            queue_label,
            icon=":material/event_repeat:",
            use_container_width=True,
            type="primary",
            disabled=due_count == 0 or st.session_state.get('is_cloud', False),
            key="welcome_srs_btn",
        ):
            due_cards = get_due_cards()
            if due_cards:
                batch_size = srs_manager.load_settings().get("batch_size", 10)
                srs_tutor = SrsTutor(due_cards, batch_size=batch_size)
                full_reset()
                srs_tutor.load_batch_into_session(st.session_state)
                st.session_state.srs_tutor    = srs_tutor
                st.session_state.srs_app_open = False
                st.rerun()

    st.divider()

    # ── Row 2: Tools ──────────────────────────────────────────────────────────
    c_gen, c_decks, c_api = st.columns(3)

    with c_gen:
        is_cloud = st.session_state.get('is_cloud', False)
        if st.button(
            "AI Course Creator",
            icon=":material/auto_awesome:",
            use_container_width=True,
            disabled=not api_key_valid and not is_cloud,
        ):
            st.session_state.generator_v5_state = 'INPUT'
            st.session_state['_scroll_top'] = True
            st.rerun()

    with c_decks:
        if st.button(
            "Manage Decks",
            icon=":material/style:",
            use_container_width=True,
            key="welcome_manage_decks_btn",
            disabled=st.session_state.get('is_cloud', False),
        ):
            st.session_state.srs_app_open = True
            st.rerun()

    with c_api:
        if st.button(
            "API Settings",
            icon=":material/key:",
            use_container_width=True,
        ):
            st.session_state.show_settings = True
            st.session_state.settings_open_tab = "api"
            st.rerun()


def _render_no_courses_fallback():
    """Render fallback UI when no courses are available."""
    st.warning("No courses found. Create one or upload an existing file.")

    api_key_valid = bool(st.session_state.get('api_adapter'))
    if st.button(
        "AI Course Creator",
        icon=":material/auto_awesome:",
        use_container_width=True,
        type="primary",
        disabled=not api_key_valid,
    ):
        st.session_state.generator_v5_state = 'INPUT'
        st.session_state['_scroll_top'] = True
        st.rerun()

    if not api_key_valid:
        st.caption("Connect an API key first — go to API Settings in the sidebar.")

    # Button to open settings
    if st.button(
        "Open Calibration Hub",
        icon=":material/tune:",
        use_container_width=True
    ):
        st.session_state.show_settings = True
        st.rerun()
    
    st.markdown("---")
    
    # Fallback file uploader
    uploaded = st.file_uploader("Or Upload JSON directly", type="json")
    if uploaded and st.button("Install"):
        save_path = Path("data/courses") / uploaded.name
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(uploaded.getbuffer())
        st.rerun()


