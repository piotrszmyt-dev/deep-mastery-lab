# Standard library
import time
import concurrent.futures
from pathlib import Path

# Third-party
import streamlit as st
from streamlit_float import *
from dotenv import load_dotenv

# UI — layout & navigation
from src.ui.ui_manager import load_active_theme
from src.ui.shortcuts import init_shortcuts
from src.ui.menu.settings_menu_render import render_settings_menu
from src.ui.components.welcome_render import render_welcome_window
from src.ui.components.sidebar_render import render_sidebar

# UI — standard lesson flow
from src.ui.components.learn_card_render import render_card_state
from src.ui.components.learn_test_render import render_test_state
from src.ui.components.learn_feedback_render import render_feedback_state

# UI — mastery mode
from src.ui.components.mastery_render import render_mastery_setup
from src.ui.components.mastery_feedback_render import render_mastery_feedback
from src.ui.components.mastery_mode_test_render import render_mastery_test
from src.ui.components.mastery_journey_render import (
    render_mastery_journey_card,
    render_mastery_journey_test,
    render_mastery_journey_done,
)

# UI — SRS mode
from src.ui.components.srs_render import render_srs_app
from src.ui.components.srs_test_render import render_srs_test
from src.ui.components.srs_feedback import render_srs_feedback
from src.ui.components.srs_journey import (
    render_srs_journey_card,
    render_srs_journey_test,
    render_srs_journey_done,
)

# UI — course generator
from src.ui.components.course_generator_render import (
    init_generator_state,
    show_generator_v5
)

# Managers
from src.managers.state_manager import initialize_session_state
from src.managers.progress_manager import ProgressManager
from src.managers.settings_manager import SettingsManager
from src.managers.keys_manager import KeysManager
from src.managers.models_manager import resolve_model_id

# Utilities & settings
from src.utils.settings_utils import load_all_settings

load_dotenv()

def track_active_time():
    """
    Calculates time elapsed since the last interaction and saves it safely.
    Ignores long breaks (idle time).
    """
    if 'current_course_path' not in st.session_state or not st.session_state.current_course_path:
        return

    current_time = time.time()
    
    if 'last_active_time' not in st.session_state:
        st.session_state.last_active_time = current_time
        return

    elapsed = current_time - st.session_state.last_active_time
    st.session_state.last_active_time = current_time
    
    if 0.5 < elapsed < 300:
        course_filename = Path(st.session_state.current_course_path).name
        st.session_state.progress_manager.update_metrics(
            course_filename, 
            time_delta=elapsed
        )

track_active_time()

# --- Page Config ---
st.set_page_config(page_title="Deep Mastery Lab", page_icon=":material/school:", layout="centered")
init_shortcuts()
float_init()

# --- SESSION STATE & MANAGERS ---
if 'keys_manager' not in st.session_state:
    try:
        _cloud_mode = bool(st.secrets.get("IS_CLOUD", False))
    except Exception:
        _cloud_mode = False
    st.session_state.keys_manager = KeysManager(cloud_mode=_cloud_mode)
    st.session_state.is_cloud = st.session_state.keys_manager.cloud_mode

if 'progress_manager' not in st.session_state:
    st.session_state.progress_manager = ProgressManager(cloud_mode=st.session_state.get('is_cloud', False))
if 'settings_manager' not in st.session_state:
    st.session_state.settings_manager = SettingsManager(cloud_mode=st.session_state.get('is_cloud', False))
if 'tutor'         not in st.session_state: st.session_state.tutor = None
if 'srs_tutor'     not in st.session_state: st.session_state.srs_tutor = None
if 'srs_app_open'  not in st.session_state: st.session_state.srs_app_open = False
if 'srs_journey_queue' not in st.session_state: st.session_state.srs_journey_queue = []
if 'srs_journey_idx'   not in st.session_state: st.session_state.srs_journey_idx = 0


if 'settings_loaded' not in st.session_state:
    load_all_settings()
    st.session_state.settings_loaded = True

# Streamlit removes widget-bound keys (txt_presentation / txt_synthesis) when the
# settings tab is not rendered. Re-populate them on every rerun from prompt_presets
# so the text areas are never blank on re-entry. Only fires when the keys are absent.
if 'txt_presentation' not in st.session_state or 'txt_synthesis' not in st.session_state:
    _active = st.session_state.get('active_preset_name', '')
    _preset = st.session_state.get('prompt_presets', {}).get(_active, {})
    st.session_state.txt_presentation = _preset.get('presentation', '')
    st.session_state.txt_synthesis    = _preset.get('synthesis', '')

load_active_theme()

# --- Course Generator Routing ---
init_generator_state()

if st.session_state.get('generator_v5_state') in ['INPUT', 'RUNNING', 'STREAMING', 'DONE', 'MODULE_REVIEW', 'RUNNING_RESUME', 'CHUNK_REVIEW']:
    show_generator_v5()
    st.stop()

# --- Background Worker ---
@st.cache_resource
def get_executor():
    return concurrent.futures.ThreadPoolExecutor(max_workers=15)

executor = get_executor()

# --- Session State Initialization ---
initialize_session_state()

# --- SIDEBAR ---
# Hide sidebar for any active SRS session — SRS is cross-course, the course sidebar is irrelevant
_immersive = (st.session_state.srs_tutor is not None or st.session_state.srs_app_open)

if _immersive:
    st.markdown(
        "<style>"
        "[data-testid='stSidebar'] { display: none !important; }"
        "[data-testid='collapsedControl'] { display: none !important; }"
        "</style>",
        unsafe_allow_html=True,
    )
elif st.session_state.tutor is not None or st.session_state.show_settings:
    render_sidebar(st.session_state.tutor)

# ==============================================================================
# MAIN ROUTER
# ==============================================================================

if st.session_state.show_settings:
    render_settings_menu()

# ==============================================================================
# SRS MODE — independent of whether a course is loaded
# ==============================================================================

elif st.session_state.srs_app_open:
    render_srs_app()

elif st.session_state.srs_tutor is not None:
    srs_tutor = st.session_state.srs_tutor
    if srs_tutor.state == "SRS_TEST":
        render_srs_test(srs_tutor)
    elif srs_tutor.state == "SRS_FEEDBACK":
        render_srs_feedback(srs_tutor)
    elif srs_tutor.state == "SRS_JOURNEY_CARD":
        render_srs_journey_card(srs_tutor)
    elif srs_tutor.state == "SRS_JOURNEY_TEST":
        render_srs_journey_test(srs_tutor)
    elif srs_tutor.state == "SRS_JOURNEY_DONE":
        render_srs_journey_done(srs_tutor)

# Welcome Screen
elif st.session_state.tutor is None:
    st.session_state.pop("_settings_tab", None)
    render_welcome_window()

else:
    st.session_state.pop("_settings_tab", None)
    tutor = st.session_state.tutor
    adapter = st.session_state.api_adapter

    # ---- Normal CARD state ----
    if tutor.state == 'CARD':
        render_card_state(tutor, adapter, executor)

    # ---- Normal TEST state ----
    elif tutor.state == 'TEST':
        render_test_state(tutor, adapter)

    # ---- Normal FEEDBACK state ----
    elif tutor.state == 'FEEDBACK':
        render_feedback_state(tutor)

    # ==========================================================================
    # MASTERY MODE STATES
    # ==========================================================================

    # ---- Mastery Setup: lesson tree + range selection ----
    elif tutor.state == 'MASTERY_SETUP':
        render_mastery_setup(tutor)

    # ---- Mastery Test: range quiz (reuses test render, goes to MASTERY_FEEDBACK) ----
    elif tutor.state == 'MASTERY_TEST':
        render_mastery_test(tutor)

    # ---- Mastery Feedback: results + "Begin Journey" button ----
    elif tutor.state == 'MASTERY_FEEDBACK':
        render_mastery_feedback(tutor)

    # ---- Mastery Journey: show cached card for failed lesson ----
    elif tutor.state == 'MASTERY_JOURNEY_CARD':
        render_mastery_journey_card(tutor)

    # ---- Mastery Journey: mini-test for failed lesson ----
    elif tutor.state == 'MASTERY_JOURNEY_TEST':
        render_mastery_journey_test(tutor)

    # ---- Mastery Journey: completion screen ----
    elif tutor.state == 'MASTERY_JOURNEY_DONE':
        render_mastery_journey_done(tutor)




