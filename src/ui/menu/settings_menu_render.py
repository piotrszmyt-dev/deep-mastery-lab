"""
Settings Menu Renderer - Main Coordinator
==========================================
Orchestrates the tabbed settings interface by delegating rendering to specialized modules.

Architecture:
    - Each tab is handled by a dedicated module in the tabs/ subdirectory
    - Main file acts as a lightweight coordinator
    - Clean separation enables independent development and testing of each tab
    - Easy to add new tabs without modifying existing code

Tabs:
    1. Courses - Course management and statistics
    2. API & AI - Model selection and API configuration
    3. Prompts - Custom AI instruction templates
    4. Quiz Parameters - Test question counts
    5. Themes - Visual theme selection
"""

import streamlit as st

from src.utils.settings_utils import save_all_settings

# Import tab render functions
from .tabs.tab_courses import render_courses_tab
from .tabs.tab_api import render_api_tab
from .tabs.tab_prompts import render_prompts_tab
from .tabs.tab_quiz_params import render_quiz_params_tab
from .tabs.tab_themes import render_themes_tab


def render_settings_menu():
    """
    Render the complete settings/calibration hub interface.
    
    Displays tabbed interface with specialized configuration panels.
    Each tab is rendered by its dedicated module for clean separation.
    
    Session State Requirements:
        - st.session_state.settings_manager
        - st.session_state.progress_manager
        - st.session_state.custom_prompts
        - st.session_state.selected_models
        - st.session_state.test_counts
        - st.session_state.active_theme_name
        - st.session_state.api_adapter
        - st.session_state.tutor (optional)
        - st.session_state.current_course_path (optional)
    """
    st.header(":material/tune: CALIBRATION HUB")
    
    # Latch any one-time tab request into a stable key so rerenders don't lose it.
    if "settings_open_tab" in st.session_state:
        st.session_state._settings_tab = st.session_state.pop("settings_open_tab")

    tab_labels = [
        ":material/database: Courses",
        ":material/smart_toy: API & AI",
        ":material/terminal: Prompts",
        ":material/settings_input_component: Quiz Parameters",
        ":material/palette: Themes"
    ]

    tab_api_first = st.session_state.get("_settings_tab") == "api"
    if tab_api_first:
        tab_labels = [tab_labels[1], tab_labels[0]] + tab_labels[2:]

    tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_labels)

    with (tab1 if tab_api_first else tab2):
        render_api_tab()
    with (tab2 if tab_api_first else tab1):
        render_courses_tab()
    with tab3:
        render_prompts_tab()
    with tab4:
        render_quiz_params_tab()
    with tab5:
        render_themes_tab()
    
    # Global save button (affects all tabs)
    st.markdown("")
    if st.button(
        "Save Global Settings",
        icon=":material/save:",
        type="primary",
        use_container_width=True
    ):
        if save_all_settings(): 
            st.toast("System configuration saved.", icon=":material/check_circle:")
        else:
            st.error("Critical: Failed to persist system configuration.", icon=":material/error:")