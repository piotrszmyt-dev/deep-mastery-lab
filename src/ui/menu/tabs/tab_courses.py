"""
Courses Tab Renderer
====================
Handles course management interface including:
- Course selection with pretty-printed names (titlecase, underscores removed)
- Progress statistics and metrics display (with HTML progress bar)
- Course management actions (Learning Mode, Download, Reset, Delete)
- AI course generator launcher
- Course upload/installation

Statistics tracked:
- Progress completion percentage (color-coded bar)
- Time spent studying
- Token usage and API costs (shown when reported by provider)
"""

import streamlit as st
import json
import shutil

from pathlib import Path
from titlecase import titlecase

from src.utils.course_utils import get_available_courses
from src.managers.state_manager import load_course, switch_course
from src.utils.settings_utils import save_all_settings
from src.managers.course_paths import get_course_dir
from src.managers.progress_manager import clear_course_progress, clear_course_metrics
from src.managers import srs_manager

def render_courses_tab():
    """
    Render the Courses management tab.

    Features:
    - Course selector with titlecase display names mapped back to real filenames
    - Progress statistics with HTML color-coded progress bar
    - Learning Mode popover (Full Generation / Raw Mode)
    - Download, Reset, and Delete popovers
    - AI Course Generator button and JSON upload interface

    Session State Requirements:
        - st.session_state.progress_manager
        - st.session_state.current_course_path (optional)
        - st.session_state.show_settings
        - st.session_state.raw_mode (optional)
    """
    
    st.markdown("#### :material/menu_book: Course Management")
    
    # ===== COURSE SELECTION & STATISTICS =====
    courses = get_available_courses()
    
    # Filter out hidden courses
    try:
        _hidden = set(st.session_state.settings_manager.load().get("hidden_courses", []))
        courses = [c for c in courses if c not in _hidden]
    except Exception:
        pass

    if courses:
        # Determine currently active course
        current_active_filename = None
        if st.session_state.current_course_path:
            current_active_filename = Path(st.session_state.current_course_path).name
        
        if not current_active_filename:
            current_active_filename = st.session_state.get('last_active_course', '')
        
        # Find index of current course
        try:
            default_idx = courses.index(current_active_filename) if current_active_filename in courses else 0
        except ValueError:
            default_idx = 0
        
        def _pretty_name(filename: str) -> str:
            """'Weather_man_I.json' → 'Weather Man I'"""
            return titlecase(Path(filename).stem.replace("_", " "))

        def _format_course(filename: str) -> str:
            try:
                overrides = st.session_state.settings_manager.load().get("course_display_names", {})
                return overrides.get(filename) or _pretty_name(filename)
            except Exception:
                return _pretty_name(filename)

        # Course selector
        selected_course = st.selectbox(
            "Select course to manage",
            courses,
            index=default_idx,
            format_func=_format_course,
            label_visibility="collapsed"
        )

        if selected_course and selected_course != current_active_filename:
            switch_course(selected_course)
            st.rerun()
        
        # ===== LOAD COURSE DATA =====
        total_elements = 0
        passed_count = 0
        
        try:
            course_path = Path("data/courses") / selected_course
            with open(course_path, 'r', encoding='utf-8') as f:
                course_data = json.load(f)
                total_elements = len(course_data)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            total_elements = 0
        
        prog_data = st.session_state.progress_manager.load(selected_course)
        if prog_data:
            passed_count = len(prog_data.get('passed_elements', []))
        
        # ===== DISPLAY STATISTICS =====
        if total_elements > 0:
            ratio = passed_count / total_elements

            # Extract metrics
            metrics = prog_data.get('metrics', {}) if prog_data else {}
            total_input = metrics.get('total_input', 0)
            total_output = metrics.get('total_output', 0)
            total_cost = metrics.get('total_cost', 0.0)
            total_seconds = metrics.get('total_time_seconds', 0)

            # Format token count
            total_tok = total_input + total_output
            if total_tok > 1_000_000:
                tok_str = f"{total_tok/1_000_000:.2f}M"
            elif total_tok > 1_000:
                tok_str = f"{total_tok/1_000:.1f}k"
            elif total_tok > 0:
                tok_str = str(total_tok)
            else:
                tok_str = "N/A"

            # Cost shown when reported by provider, N/A when zero (provider doesn't track it)
            cost_str = f"${total_cost:.4f}" if total_cost > 0 else "N/A"

            # Format time
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)

            # Build display strings
            str_progress = f"Progress: <b>{passed_count}/{total_elements} ({ratio:.1%})</b>"
            str_time = f"Time Spent: <b>{hours}h {minutes}m</b>"
            str_cost = f"Tokens: <b>{tok_str}</b> | Cost: <b>{cost_str}</b>"

            # Display statistics in 3 columns
            caption_style = "text-align: center; font-size: 0.8em; opacity: 0.7; margin-bottom: 10px;"

            c1, c2, c3 = st.columns([1.2, 0.8, 1.2])
            with c1:
                st.markdown(f'<div style="{caption_style}">{str_progress}</div>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<div style="{caption_style}">{str_time}</div>', unsafe_allow_html=True)
            with c3:
                st.markdown(f'<div style="{caption_style}">{str_cost}</div>', unsafe_allow_html=True)

            # Progress bar — hue 0 (red) → 120 (green) based on completion ratio
            hue_value = int(ratio * 120)
            st.markdown(f"""
                <div class="progress-container">
                    <div class="progress-fill" style="--bar-hue: {hue_value}; width: {ratio*100}%;"></div>
                </div>
                """, unsafe_allow_html=True)
        
        # ===== COURSE ACTIONS =====
        col_act1, col_act2, col_act3, col_act4 = st.columns([1.2, 1, 1, 1])
        
        with col_act1:
            with st.popover("Learning Mode", icon=":material/school:", use_container_width=True):
                st.markdown("**Select Learning Mode**")
                
                if st.button(
                    "Full Generation Mode",
                    icon=":material/auto_awesome:",
                    help="AI generates full lesson presentations",
                    use_container_width=True,
                    type="primary" if not st.session_state.get('raw_mode') else "secondary"
                ):
                    st.session_state.raw_mode = False
                    save_all_settings()
                    st.session_state.show_settings = False
                    switch_course(selected_course)
                    st.rerun()
                
                if st.button(
                    "Raw Mode",
                    icon=":material/source:",
                    help="Shows source material directly, only questions are generated",
                    use_container_width=True,
                    type="primary" if st.session_state.get('raw_mode') else "secondary"
                ):
                    st.session_state.raw_mode = True
                    save_all_settings()
                    st.session_state.show_settings = False
                    switch_course(selected_course)
                    st.rerun()
        
        with col_act2:
            # DOWNLOAD - Export course materials
            with st.popover("Download", icon=":material/download:", use_container_width=True):
                st.markdown("**Export Course Materials**")
                st.info("You can download the source course file here. Additionally, in the future, the .apkg deck with all generated questions will also be available.")
                
                # Download source JSON
                try:
                    course_path = Path("data/courses") / selected_course
                    if course_path.exists():
                        with open(course_path, "rb") as f:
                            file_data = f.read()
                        
                        st.download_button(
                            label="Download Source (.json)",
                            data=file_data,
                            file_name=selected_course,
                            mime="application/json",
                            icon=":material/data_object:",
                            type="secondary",
                            use_container_width=True
                        )
                    else:
                        st.warning("Source file not found on disk.")
                except Exception as e:
                    st.error(f"Error preparing download: {e}")
                
                # Placeholder for Anki deck
                st.button(
                    "Download Anki Deck (.apkg)",
                    icon=":material/school:",
                    disabled=True,
                    use_container_width=True,
                    help="Coming soon: Seamless export to Anki."
                )
        
        with col_act3:
            is_cloud = st.session_state.get('is_cloud', False)
            btn_disabled = not (passed_count > 0) or is_cloud
            with st.popover("Reset", icon=":material/restore:", use_container_width=True, disabled=btn_disabled):
                st.write(f"Clear learning data for **{_format_course(selected_course)}**?")

                col_p, col_m = st.columns(2)
                with col_p:
                    if st.button("Clear Progress", icon=":material/restore:", type="primary",
                                 use_container_width=True, key="reset_progress_btn"):
                        clear_course_progress(selected_course)
                        load_course(selected_course)
                        st.rerun()
                with col_m:
                    if st.button("Clear Metrics", icon=":material/analytics:", type="secondary",
                                 use_container_width=True, key="reset_metrics_btn"):
                        clear_course_metrics(selected_course)
                        st.rerun()
        
        with col_act4:
            with st.popover("Delete", icon=":material/delete_forever:", use_container_width=True,
                            disabled=st.session_state.get('is_cloud', False)):
                st.warning("**Permanent Deletion**")
                st.write("Deletes the course file, all cached content, progress, metrics, and SRS review data.")

                if st.button("Confirm Purge", icon=":material/dangerous:", type="primary",
                             use_container_width=True, key="confirm_purge_btn"):
                    # Delete course JSON
                    (Path("data/courses") / selected_course).unlink(missing_ok=True)
                    # Delete entire course_data/<stem>/ folder atomically
                    course_dir = get_course_dir(selected_course)
                    if course_dir.exists():
                        shutil.rmtree(course_dir)
                    # Remove SRS schedule rows for this course
                    srs_manager.reset_srs(selected_course)
                    st.session_state.tutor = None
                    st.session_state.current_course_path = None
                    st.rerun()
    
    else:
        st.info("No Courses Available")
    
    # ===== ADD NEW COURSE SECTION =====
    st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)
    st.markdown("#### :material/add_circle: Add New Course")
    
    # AI Course Generator
    if st.button("AI Course Generator", icon=":material/auto_awesome:", use_container_width=True,
                 disabled=st.session_state.get('is_cloud', False)):
        st.session_state.generator_v5_state = 'INPUT'
        st.rerun()
    
    # ===== COURSE UPLOAD =====
    with st.container(border=True):
        st.markdown("**:material/upload_file: INSTALL COURSE FROM (.json)**")
        
        uploaded = st.file_uploader(
            "Browse JSON Archive",
            type="json",
            label_visibility="collapsed"
        )
        
        if uploaded:
            save_path = Path("data/courses") / uploaded.name
            with open(save_path, "wb") as f:
                f.write(uploaded.getbuffer())
            st.success(f"Installed: {uploaded.name}")
            st.rerun()