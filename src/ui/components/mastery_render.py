"""
Mastery Mode Renderer
=====================
Setup screen for Mastery Mode - course tree with checkboxes, question pool counts,
range selection, and mastery test launch.

Flow:
    1. User opens Mastery Mode
    2. Config panel shown at top (metrics, question count, Select All / launch)
    3. Course tree shown below with pool counts per lesson
    4. User selects lessons by module checkbox or individually
    5. "Start Mastery Test" pulls questions, resets state → MASTERY_TEST
"""

import streamlit as st
from pathlib import Path

from src.managers.cache_manager import load_question_pools, get_questions_for_range
from src.managers.state_manager import full_reset


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def render_mastery_setup(tutor):
    """
    Render the Mastery Mode setup screen.

    Args:
        tutor: SimpleTutor instance
    """
    # --- Header ---
    col_title, col_back = st.columns([4, 1], vertical_alignment="center")
    with col_title:
        st.markdown("## Mastery Mode")
    with col_back:
        if st.button(":material/arrow_back: Exit", use_container_width=True, key="mastery_exit"):
            st.session_state.mastery_questions = []
            st.session_state.mastery_journey_queue = []
            st.session_state.mastery_journey_idx = 0
            st.session_state.mastery_journey_active = False
            full_reset()
            tutor.state = 'CARD'
            st.session_state.show_settings = True
            st.rerun()

    if not st.session_state.get('current_course_path'):
        st.warning("No course loaded.")
        return

    course_filename = Path(st.session_state.current_course_path).name
    pools = load_question_pools(course_filename)

    # Ensure selection dict exists in session
    if 'mastery_selected' not in st.session_state:
        st.session_state.mastery_selected = {}

    # 1. RESERVE SPACE AT THE TOP FOR CONFIG
    config_container = st.container()
    

    # --- Course Tree with Checkboxes ---
    st.markdown("### Select Question Pool")
    modules = _build_module_structure(tutor)
    
    # 2. RUN THE TREE LOGIC TO GET TOTALS
    total_available_questions = _render_selection_tree(tutor, modules, pools)
    ignored = st.session_state.get('ignored_elements', set())
    eligible_ids = [
        eid for eid, d in tutor.syllabus.items()
        if d.get('type') == 'lesson' 
        and pools.get(eid, {}).get('pool_size', 0) > 0
        and eid not in ignored
    ]
    selected_ids = _get_selected_ids_with_pools(pools)

    # 3. DRAW THE CONFIG INSIDE THE TOP CONTAINER
    with config_container:
        _render_config_and_launch(
            tutor, 
            course_filename, 
            selected_ids,  
            total_available_questions,
            eligible_ids
        )


# ============================================================================
# COURSE TREE RENDERING
# ============================================================================

def _build_module_structure(tutor):
    """Group syllabus elements by module."""
    modules = {}
    for eid, data in tutor.syllabus.items():
        if data.get('type') == 'final_test' or eid in ('FINAL_TEST', '_master_index'):
            continue
        m_id = data.get('module_id', eid.split('-')[0])
        if m_id not in modules:
            modules[m_id] = []
        modules[m_id].append((eid, data))
    return modules


def _render_selection_tree(tutor, modules, pools):
    """
    Render the full lesson selection tree using expanders.

    Returns:
        int: Total available questions from checked lessons
    """
    total_available = 0

    with st.container(border=False, key='mastery_tree'):
        for m_id, elements in modules.items():
            total_available += _render_module_expander(m_id, elements, pools)

    return total_available


def _render_module_expander(m_id, elements, pools):
    """
    Render one module as an expander with a module-level checkbox beside it.
    Only eligible lessons (type=lesson, pool exists, not ignored) are counted
    and selectable. The checkbox key encodes all_checked to force re-render on
    selection change.

    Returns:
        int: Total available questions from checked lessons in this module
    """
    m_title = elements[0][1].get('module_title', 'Module')
    module_has_any_pool = any(
        pools.get(eid, {}).get('pool_size', 0) > 0 for eid, _ in elements
    )

    ignored = st.session_state.get('ignored_elements', set())
    eligible = [
        eid for eid, d in elements
        if pools.get(eid, {}).get('pool_size', 0) > 0
        and d.get('type') == 'lesson'
        and eid not in ignored 
    ]
    all_checked = (
        len(eligible) > 0
        and all(st.session_state.mastery_selected.get(eid, False) for eid in eligible)
    )

    module_total_q = sum(pools.get(eid, {}).get('pool_size', 0) for eid in eligible)
    q_label = f"  • [{module_total_q} Qs]" if module_total_q > 0 else ""

    total_available = 0

    col_cb, col_exp = st.columns([0.01, 0.99])

    with col_cb:
        # Added a tiny bit of vertical space so the checkbox aligns with the expander header
        new_all = st.checkbox(
            "Select module",
            value=all_checked,
            key=f"mastery_mod_{m_id}_{all_checked}",  
            label_visibility="collapsed",
            disabled=not module_has_any_pool
        )
        if new_all != all_checked:
            for eid in eligible:
                st.session_state.mastery_selected[eid] = new_all
            st.rerun()

    with col_exp:
        with st.expander(f"❖ {m_id}: {m_title}{q_label}"):
            total_available = _render_concept_groups(elements, pools)

    return total_available


def _render_concept_groups(elements, pools):
    """
    Render lessons inside a module expander.
    Shows module_subtitle as static info, then individual lesson checkboxes.
    Skips checkpoints and synthesis nodes.
    """
    total_available = 0
    
    subtitle = elements[0][1].get('module_subtitle', '')
    if subtitle:
        st.caption(subtitle)

    ignored = st.session_state.get('ignored_elements', set())

    for eid, data in elements:
        if data.get('type') != 'lesson':
            continue
        if eid in ignored:                                  # ← add
            continue 
        pool_size = pools.get(eid, {}).get('pool_size', 0)
        total_available += _render_lesson_row(eid, data, pool_size)

    return total_available

def _render_lesson_row(eid, data, pool_size):
    """
    Render a single lesson row: checkbox column | name column.
    """

    title = data.get('lesson_title', eid)

    has_pool = pool_size > 0
    is_checked = st.session_state.mastery_selected.get(eid, False)

    pool_label = f" • [{pool_size} Qs]" if has_pool else " :material/error_outline:"
    display_text = f"{title} {pool_label}"

    new_checked = st.checkbox(
        display_text, # Markdown handles the text styling and icons
        value=is_checked if has_pool else False,
        key=f"mastery_cb_{eid}_{is_checked}",
        disabled=not has_pool
    )
    
    if new_checked != is_checked:
        st.session_state.mastery_selected[eid] = new_checked
        st.rerun()

    return pool_size if (has_pool and new_checked) else 0


def _get_selected_ids_with_pools(pools):
    """Return list of selected lesson IDs that have a question pool."""
    return [
        eid for eid, checked in st.session_state.mastery_selected.items()
        if checked and pools.get(eid, {}).get('pool_size', 0) > 0
    ]

# ============================================================================
# CONFIG PANEL + LAUNCH
# ============================================================================

def _render_config_and_launch(tutor, course_filename, selected_ids, total_available, eligible_ids=None):
    """Render the config panel: metrics, question count input, Select All toggle, and launch button."""
    
    # --- 1. State Summary (Metrics) ---
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Selected lessons", len(selected_ids))
    with col2:
        st.metric("Available questions", total_available)

    # --- 2. Configuration (Number Input) ---
    max_q = max(1, total_available)
    default_q = min(30, max_q) if total_available > 0 else 1

    if 'mastery_q_count' not in st.session_state:
        st.session_state.mastery_q_count = default_q
    else:
        st.session_state.mastery_q_count = min(st.session_state.mastery_q_count, max_q)

    col_input, col_btn = st.columns([0.7, 0.3], vertical_alignment="bottom")

    all_selected = (
        len(eligible_ids or []) > 0
        and all(st.session_state.mastery_selected.get(eid, False) for eid in (eligible_ids or []))
    )

    with col_input:
        q_count = st.number_input(
            "Questions to answer",
            min_value=1,
            max_value=max_q,
            step=5,
            key="mastery_q_count",
            disabled=(total_available == 0)
        )
    
    with col_btn:
        btn_label = "Deselect All" if all_selected else "Select All"
        if st.button(btn_label, use_container_width=True, type="secondary", disabled=not eligible_ids):
            new_val = not all_selected
            for eid in eligible_ids:
                st.session_state.mastery_selected[eid] = new_val
            st.rerun()

    no_selection = len(selected_ids) == 0 or total_available == 0
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button(
        "Start Mastery Test",
        icon=":material/rocket_launch:",
        type="primary",
        use_container_width=True,
        disabled=no_selection,

    ):
        _launch_mastery_test(tutor, course_filename, selected_ids, int(q_count))



# ============================================================================
# LAUNCH HANDLER
# ============================================================================

def _launch_mastery_test(tutor, course_filename, selected_ids, q_count):
    """
    Pull questions from range pools and enter MASTERY_TEST state.

    Args:
        tutor: SimpleTutor instance
        course_filename: e.g. "Aurora.json"
        selected_ids: list of lesson IDs to pull questions from
        q_count: number of questions for this mastery test
    """

    questions = get_questions_for_range(course_filename, selected_ids, q_count)

    if not questions:
        st.error(
            "Could not load questions from the selected lessons. "
            "Try regenerating pools by completing those lessons normally."
        )
        return

    # Store mastery-specific state
    full_reset()
    st.session_state.mastery_questions = list(questions)
    st.session_state.mastery_selected_ids = selected_ids

    # Feed into the standard test pipeline
    st.session_state.questions = list(questions)
    st.session_state.answers = [None] * len(questions)
    st.session_state.current_question_idx = 0
    st.session_state.is_quick_test = True 

    tutor.state = 'MASTERY_TEST'
    st.rerun()