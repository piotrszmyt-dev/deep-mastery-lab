"""
SRS App — Deck List Screen
===========================
The Anki-style home screen for the SRS review system.

Layout (top to bottom):
  1. Header: "Daily Review" + Back button
  2. Stats row: Total Due | Selected Due
  3. Batch input + Start Review button
  4. Tools row: Group | Ungroup | Reset Progress | Delete
  5. Course list:
       — Groups first (alphabetically by group name, collapsed expanders)
       — Ungrouped courses below (alphabetically by display name)

Course ordering uses alphabetical sort so naming groups with "_" prefix
(e.g. "_Main Study") naturally floats them above regular letters.

Session state keys owned here:
  srs_selected  — {course_name: bool}  (also used for queue selection)
  srs_settings  — mirrors disk srs_settings.json in session
"""

import streamlit as st
from pathlib import Path
from titlecase import titlecase

from src.utils.course_utils import get_available_courses
from src.managers import srs_manager
from src.core.srs_tutor import SrsTutor
from src.managers.state_manager import full_reset


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def render_srs_app():
    """Render the SRS deck-list home screen."""
    _init_srs_session_state()

    with st.container(key="generator_card"):
        col_title, col_back = st.columns([4, 1], vertical_alignment="center")
        with col_title:
            st.markdown(
                '<div class="card-title"><span class="material-icons">event_available</span> Daily Review</div>',
                unsafe_allow_html=True
            )
        with col_back:
            if st.button(":material/arrow_back: Exit", use_container_width=True, key="srs_exit"):
                st.session_state.srs_app_open = False
                st.session_state.tutor        = None
                st.rerun()

        due_per_course = srs_manager.get_due_count_per_course()
        courses        = sorted(get_available_courses())
        settings       = st.session_state.srs_settings

        # Reserve top container for stats + launch (rendered after tree so we know totals)
        top_container = st.container()

        # ── Course tree ──────────────────────────────────────────────────────────
        st.markdown("### Select Decks")
        selected_due, total_due = _render_course_tree(courses, settings, due_per_course)

        # ── Top container: stats + launch ────────────────────────────────────────
        with top_container:
            _render_stats_and_launch(settings, selected_due, total_due)


# ============================================================================
# SESSION STATE
# ============================================================================

def _init_srs_session_state():
    courses = get_available_courses()
    course_set = set(courses)

    if "srs_selected" not in st.session_state:
        st.session_state.srs_selected = {c: True for c in courses}
    else:
        # Add new courses, prune courses that no longer exist
        for c in courses:
            if c not in st.session_state.srs_selected:
                st.session_state.srs_selected[c] = True
        for c in list(st.session_state.srs_selected):
            if c not in course_set:
                del st.session_state.srs_selected[c]

    # Always reload from disk so changes made elsewhere in the session are visible
    st.session_state.srs_settings = srs_manager.load_settings()


# ============================================================================
# HIDDEN COURSES HELPERS
# ============================================================================

def _get_hidden_courses() -> set:
    """Lazy-load hidden course filenames from settings.json (cached per session)."""
    if "hidden_courses_cache" not in st.session_state:
        try:
            data = st.session_state.settings_manager.load()
            st.session_state.hidden_courses_cache = set(data.get("hidden_courses", []))
        except Exception:
            st.session_state.hidden_courses_cache = set()
    return st.session_state.hidden_courses_cache


def _save_hidden_courses(hidden: set) -> None:
    """Persist hidden courses to settings.json and update session cache."""
    try:
        data = st.session_state.settings_manager.load()
        data["hidden_courses"] = sorted(hidden)
        st.session_state.settings_manager.save(data)
        st.session_state.hidden_courses_cache = set(hidden)
    except Exception:
        pass


def _get_display_names() -> dict:
    """Lazy-load course display name overrides from settings.json (cached per session)."""
    if "display_names_cache" not in st.session_state:
        try:
            data = st.session_state.settings_manager.load()
            st.session_state.display_names_cache = data.get("course_display_names", {})
        except Exception:
            st.session_state.display_names_cache = {}
    return st.session_state.display_names_cache


def _save_display_names(names: dict) -> None:
    """Persist display name overrides to settings.json and update session cache."""
    try:
        data = st.session_state.settings_manager.load()
        data["course_display_names"] = names
        st.session_state.settings_manager.save(data)
        st.session_state.display_names_cache = names
    except Exception:
        pass


def _display_name(course: str) -> str:
    """Return custom display name if set, otherwise derive from filename."""
    return _get_display_names().get(course) or _pretty_name(course)


# ============================================================================
# STATS + LAUNCH
# ============================================================================

def _render_stats_and_launch(settings, selected_due, total_due):
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Due", total_due)
    with col2:
        st.metric("Selected Due", selected_due)

    col_input, col_btn = st.columns([0.55, 0.45], vertical_alignment="bottom")

    with col_input:
        saved_batch = settings.get("batch_size", 10)
        batch_size = st.number_input(
            "Questions per batch",
            min_value=5,
            max_value=100,
            value=saved_batch,
            step=5,
            key="srs_batch_size",
            disabled=(selected_due == 0),
        )
        if int(batch_size) != saved_batch:
            settings["batch_size"] = int(batch_size)
            srs_manager.save_settings(settings)
            st.session_state.srs_settings = settings

    with col_btn:
        selected_courses = [c for c, v in st.session_state.srs_selected.items() if v]
        if st.button(
            f"Start Review  [{selected_due}]",
            icon=":material/play_circle:",
            type="primary",
            use_container_width=True,
            disabled=(selected_due == 0),
            key="srs_start_btn",
        ):
            _launch_srs_session(selected_courses, int(batch_size))

    st.markdown("<br>", unsafe_allow_html=True)
    _render_tools_row(settings)


def _launch_srs_session(course_names: list, batch_size: int):
    due_cards = srs_manager.get_due_cards(course_names)
    if not due_cards:
        st.toast("No due cards found.", icon=":material/inbox:")
        return

    srs_tutor = SrsTutor(due_cards, batch_size=batch_size)
    full_reset()
    srs_tutor.load_batch_into_session(st.session_state)
    st.session_state.srs_tutor    = srs_tutor
    st.session_state.srs_app_open = False
    st.rerun()


# ============================================================================
# TOOLS ROW
# ============================================================================

def _render_tools_row(settings):
    selected = [c for c, v in st.session_state.srs_selected.items() if v]
    grouped  = _get_grouped_courses(settings)
    selected_in_group = [c for c in selected if c in grouped]

    t0, t1, t2, t3, t4, t5, t6 = st.columns(7)

    with t0:
        any_selected = bool(selected)
        if st.button(
            "",
            icon=":material/deselect:" if any_selected else ":material/select_all:",
            help="Deselect all" if any_selected else "Select all",
            use_container_width=True,
            key="srs_toggle_all_btn",
        ):
            all_courses = get_available_courses()
            new_value = not any_selected
            for c in all_courses:
                st.session_state.srs_selected[c] = new_value
            st.rerun()

    with t1:
        _render_group_button(selected, settings)

    with t2:
        if st.button(
            "",
            icon=":material/folder_off:",
            help="Remove selected from their group",
            use_container_width=True,
            key="srs_ungroup_btn",
            disabled=not selected_in_group,
        ):
            _remove_from_groups(selected_in_group, settings)

    with t3:
        _render_reset_button(selected)

    with t4:
        _render_delete_button(selected)

    with t5:
        _render_visibility_button(selected)

    with t6:
        _render_rename_button(selected)


def _render_group_button(selected: list, settings: dict):
    with st.popover(
        "",
        icon=":material/create_new_folder:",
        help="Group selected courses",
        use_container_width=True,
        disabled=len(selected) < 1,
    ):
        existing_groups = {k: v for k, v in settings.get("groups", {}).items() if v}

        # ── Create new group ─────────────────────────────────────────────────
        st.markdown("**Create Group**")
        group_name = st.text_input("Group name", key="srs_group_name_input", placeholder='e.g. "_Main Study"')
        if st.button("Create", icon=":material/create_new_folder:", key="srs_create_group_btn",
                     type="primary", use_container_width=True, disabled=not group_name.strip()):
            _move_to_group(selected, group_name.strip(), settings)

        # ── Add to existing group ────────────────────────────────────────────
        if existing_groups:
            st.divider()
            st.markdown("**Add to Group**")
            for gname in sorted(existing_groups.keys()):
                col_name, col_btn = st.columns([0.75, 0.25], vertical_alignment="bottom")
                with col_name:
                    st.caption(gname)
                with col_btn:
                    if st.button(
                        "",
                        icon=":material/add:",
                        key=f"srs_add_to_group_{gname}",
                        use_container_width=True,
                    ):
                        _move_to_group(selected, gname, settings)


def _move_to_group(courses: list, group_name: str, settings: dict):
    groups = settings.get("groups", {})
    if group_name not in groups:
        groups[group_name] = []
    for c in courses:
        if c not in groups[group_name]:
            groups[group_name].append(c)
        for other_name, members in groups.items():
            if other_name != group_name and c in members:
                members.remove(c)
    settings["groups"] = groups
    srs_manager.save_settings(settings)
    st.session_state.srs_settings = settings
    st.rerun()


def _remove_from_groups(courses_to_remove: list, settings: dict):
    groups = settings.get("groups", {})
    for members in groups.values():
        for c in courses_to_remove:
            if c in members:
                members.remove(c)
    # Clean up empty groups
    settings["groups"] = {k: v for k, v in groups.items() if v}
    srs_manager.save_settings(settings)
    st.session_state.srs_settings = settings
    st.rerun()


def _render_reset_button(selected: list):
    with st.popover(
        "",
        icon=":material/restart_alt:",
        help="Reset SRS progress for selected courses",
        use_container_width=True,
        disabled=not selected,
    ):
        st.markdown(f"**Reset SRS for {len(selected)} course(s)?**")
        st.caption("This clears scheduling data only. Lesson progress and question pools are kept.")
        if st.button("Reset", icon=":material/restart_alt:", key="srs_reset_confirm",
                     type="primary", use_container_width=True):
            for c in selected:
                srs_manager.reset_srs(c)
            st.toast("SRS progress reset.", icon=":material/check_circle:")
            st.rerun()


def _render_delete_button(selected: list):
    with st.popover(
        "",
        icon=":material/delete_forever:",
        help="Delete selected courses and all their data",
        use_container_width=True,
        disabled=not selected,
    ):
        st.markdown(f"**Permanently delete {len(selected)} course(s)?**")
        st.caption("This removes the course JSON, all cached cards, questions, progress, and SRS data.")
        if st.button("Delete Forever", icon=":material/delete_forever:", key="srs_delete_confirm",
                     type="primary", use_container_width=True):
            _delete_courses(selected)


def _render_visibility_button(selected: list):
    hidden = _get_hidden_courses()
    all_hidden    = selected and all(c in hidden for c in selected)
    any_hidden    = any(c in hidden for c in selected)
    help_text = "Show in course selectors" if any_hidden else "Hide from course selectors"
    icon      = ":material/visibility:" if any_hidden else ":material/visibility_lock:"

    with st.popover(
        "",
        icon=icon,
        help=help_text,
        use_container_width=True,
        disabled=not selected,
    ):
        if all_hidden:
            st.markdown(f"**Unhide {len(selected)} course(s)?**")
            st.caption("They will reappear in the course selector on the Welcome screen and Settings.")
            if st.button("Unhide", icon=":material/visibility:", key="srs_unhide_confirm",
                         type="primary", use_container_width=True):
                for c in selected:
                    hidden.discard(c)
                _save_hidden_courses(hidden)
                st.rerun()
        else:
            st.markdown(f"**Hide {len(selected)} course(s)?**")
            st.caption("Hidden courses stay in SRS review but won't appear in the Welcome or Settings course selectors.")
            if st.button("Hide", icon=":material/visibility_lock:", key="srs_hide_confirm",
                         type="primary", use_container_width=True):
                for c in selected:
                    hidden.add(c)
                _save_hidden_courses(hidden)
                st.rerun()


def _render_rename_button(selected: list):
    single = len(selected) == 1
    with st.popover(
        "",
        icon=":material/edit_note:",
        help="Rename course display name",
        use_container_width=True,
        disabled=not single,
    ):
        if single:
            course = selected[0]
            current = _get_display_names().get(course, "")
            st.markdown(f"**Rename: {_pretty_name(course)}**")
            st.caption("Sets a display name used in all course selectors. Does not modify the course file.")
            new_name = st.text_input(
                "Display name",
                value=current,
                placeholder=_pretty_name(course),
                key="srs_rename_input",
            )
            if st.button("Save", icon=":material/save:", key="srs_rename_save",
                         type="primary", use_container_width=True,
                         disabled=not new_name.strip()):
                names = _get_display_names().copy()
                names[course] = new_name.strip()
                _save_display_names(names)
                st.rerun()
            if st.button("Reset to Default", icon=":material/restore:", key="srs_rename_clear",
                         use_container_width=True, disabled=not current):
                names = _get_display_names().copy()
                names.pop(course, None)
                _save_display_names(names)
                st.rerun()


def _delete_courses(course_names: list):
    import shutil
    settings = st.session_state.srs_settings
    groups   = settings.get("groups", {})

    for course_name in course_names:
        # SRS records
        srs_manager.reset_srs(course_name)
        # Remove from groups
        for members in groups.values():
            if course_name in members:
                members.remove(course_name)
        # Remove course JSON
        course_path = Path("data/courses") / course_name
        if course_path.exists():
            course_path.unlink()
        # Remove course_data directory
        stem = Path(course_name).stem
        data_dir = Path("data/course_data") / stem
        if data_dir.exists():
            shutil.rmtree(data_dir, ignore_errors=True)
        # Deselect
        st.session_state.srs_selected.pop(course_name, None)

    # Remove from hidden set
    hidden = _get_hidden_courses()
    for course_name in course_names:
        hidden.discard(course_name)
    _save_hidden_courses(hidden)

    # Remove display name overrides
    names = _get_display_names().copy()
    for course_name in course_names:
        names.pop(course_name, None)
    _save_display_names(names)

    settings["groups"] = {k: v for k, v in groups.items() if v}
    srs_manager.save_settings(settings)
    st.session_state.srs_settings = settings
    st.toast(f"Deleted {len(course_names)} course(s).", icon=":material/check_circle:")
    st.rerun()


# ============================================================================
# COURSE TREE
# ============================================================================

def _render_course_tree(courses: list, settings: dict, due_per_course: dict):
    """
    Render groups (alphabetical) then ungrouped courses (alphabetical).
    Returns (selected_due, total_due) totals.
    """
    groups    = settings.get("groups", {})
    grouped   = _get_grouped_courses(settings)
    ungrouped = sorted([c for c in courses if c not in grouped])

    total_due    = sum(due_per_course.values())
    selected_due = 0

    with st.container(key="srs_deck_list", border=False):
        # ── Groups ──────────────────────────────────────────────────────────
        for group_name in sorted(groups.keys()):
            members = [c for c in groups[group_name] if c in courses]
            if not members:
                continue
            selected_due += _render_group_expander(group_name, members, due_per_course)

        # ── Ungrouped ────────────────────────────────────────────────────────
        if ungrouped and any(groups[g] for g in groups if any(c in courses for c in groups[g])):
            st.divider()
        for course in ungrouped:
            selected_due += _render_course_row(course, due_per_course)

    return selected_due, total_due


def _render_group_expander(group_name: str, members: list, due_per_course: dict) -> int:
    """Render one group as an expander with a select-all checkbox beside it."""
    group_due = sum(due_per_course.get(c, 0) for c in members)
    all_checked = all(st.session_state.srs_selected.get(c, False) for c in members)
    q_label = f"  • [{group_due}]" if group_due else ""

    selected_due = 0
    col_cb, col_exp = st.columns([0.01, 0.99])

    with col_cb:
        new_all = st.checkbox(
            "Select group",
            value=all_checked,
            key=f"srs_grp_{group_name}_{all_checked}",
            label_visibility="collapsed",
        )
        if new_all != all_checked:
            for c in members:
                st.session_state.srs_selected[c] = new_all
            st.rerun()

    with col_exp:
        with st.expander(f"❖ {group_name}{q_label}"):
            with st.container(key=f"srs_grouped_elements_{group_name}"):
                for course in sorted(members):
                    selected_due += _render_course_row(course, due_per_course)

    return selected_due


def _render_course_row(course: str, due_per_course: dict) -> int:
    """Render a single course checkbox row. Returns due count if selected."""
    due        = due_per_course.get(course, 0)
    label      = _display_name(course)
    badge      = f" • [{due}]" if due else ""
    is_hidden  = course in _get_hidden_courses()
    lock_icon  = " :material/visibility_lock:" if is_hidden else ""
    is_checked = st.session_state.srs_selected.get(course, False)

    with st.container(key=f"srs_cb_{course}_{is_checked}"):
        col_cb, col_label = st.columns([0.05, 0.95], vertical_alignment="center")
        with col_cb:
            new_checked = st.checkbox(
                label,
                value=is_checked,
                key=f"srs_check_{course}_{is_checked}",
                label_visibility="collapsed",
            )
        with col_label:
            st.markdown(f"{label}{badge}{lock_icon}")

    if new_checked != is_checked:
        st.session_state.srs_selected[course] = new_checked
        st.rerun()

    return due if new_checked else 0


# ============================================================================
# HELPERS
# ============================================================================

def _get_grouped_courses(settings: dict) -> set:
    """Return set of all course names that belong to any group."""
    grouped = set()
    for members in settings.get("groups", {}).values():
        grouped.update(members)
    return grouped


def _pretty_name(filename: str) -> str:
    return titlecase(Path(filename).stem.replace("_", " "))
