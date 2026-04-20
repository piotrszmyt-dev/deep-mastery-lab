"""
Quiz Parameters Tab Renderer
=============================
Configures question counts for each assessment stage and the AI lesson context window.

Assessment stages:
    - Lesson          — questions after each individual lesson
    - Checkpoint      — mid-module progress check
    - Module Test     — comprehensive end-of-module assessment
    - Final Test      — end-of-course cumulative assessment

Context window:
    Controls how many previous lessons the AI looks back when generating
    cards and questions. Set to 0 to disable cross-lesson context.
"""

import streamlit as st

def render_quiz_params_tab():
    # === ROW 1: Lesson Parameters ===
    st.markdown("#### :material/menu_book: Lesson Parameters")
    st.caption(
        "Control how many questions you see per lesson and how far back the AI looks for context. "
        "By default all available questions are shown for complete coverage — lower the limit if you prefer a lighter session."
    )

    col1, col2 = st.columns(2)
    with col1:
        st.session_state.lesson_max_questions = st.number_input(
            "Max Questions per Lesson",
            min_value=0, max_value=50,
            value=st.session_state.get('lesson_max_questions', 0),
            help="Maximum questions shown per lesson test. 0 = show all (full coverage mode).",
            key="quiz_lesson_max"
        )
    with col2:
        st.session_state.lesson_context_window = st.number_input(
            "Lesson Context Window",
            min_value=0, max_value=10,
            value=st.session_state.get('lesson_context_window', 6),
            help="How many previous lessons the AI looks back when generating cards and questions. Set to 0 to disable.",
            key="quiz_context"
        )

    st.divider()

    # === ROW 2: Test question counts ===
    st.markdown("#### :material/quiz: Test Settings")
    st.caption("Define question counts for each assessment stage")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.session_state.test_counts['module_checkpoint'] = st.number_input(
            "Checkpoint",
            min_value=3, max_value=50, value=st.session_state.test_counts.get('module_checkpoint', 10),
            help="Mid-module checkpoint test",
            key="quiz_checkpoint"
        )
    with col2:
        st.session_state.test_counts['module_synthesis'] = st.number_input(
            "Module Test",
            min_value=5, max_value=100, value=st.session_state.test_counts.get('module_synthesis', 20),
            help="Comprehensive test at end of module",
            key="quiz_module"
        )
    with col3:
        st.session_state.test_counts['final_test'] = st.number_input(
            "Final Test",
            min_value=10, max_value=200, value=st.session_state.test_counts.get('final_test', 50),
            help="End-of-course final assessment",
            key="quiz_final"
        )