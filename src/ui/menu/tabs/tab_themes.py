"""
Themes Tab Renderer
===================
Handles visual theme/environment selection for the application interface.

Features:
- Dynamic theme discovery from assets directory
- Automatic theme application on selection
- Auto-save functionality
- Immediate UI refresh on theme change
"""

import streamlit as st

from src.ui.ui_manager import get_theme_map
from src.utils.settings_utils import save_all_settings



def render_themes_tab():
    """
    Render the Themes configuration tab.
    
    Features:
    - Dynamic theme selection from available themes
    - Automatic detection of currently active theme
    - Immediate application and save on selection change
    - System-wide UI refresh on theme switch
    
    Session State Requirements:
        - st.session_state.active_theme_name
        - st.session_state.settings_manager
    """
    
    # ===== HEADER =====
    st.markdown("#### :material/palette: Appearance")
    st.caption("Pick a look you like — there are plenty to choose from.")
    
    # ===== THEME SELECTION =====

    # Get available themes dynamically
    theme_map = get_theme_map()
    theme_options = sorted(theme_map.keys())
    
    # Find current theme index
    current_index = 0
    if st.session_state.active_theme_name in theme_options:
        current_index = theme_options.index(st.session_state.active_theme_name)
    
    # Theme selector
    selected_theme = st.selectbox(
        "Theme",
        theme_options,
        index=current_index,
        help="Changes the color scheme of the interface",
        key="theme_selector"
    )
    
    # ===== APPLY THEME ON CHANGE =====
    if selected_theme != st.session_state.active_theme_name:
        st.session_state.active_theme_name = selected_theme
        save_all_settings()
        st.toast(f"Theme set to: {selected_theme}", icon=":material/palette:")
        st.rerun()
    
    