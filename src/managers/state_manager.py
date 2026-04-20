"""
State Manager
=============
Manages Streamlit session state initialization, persistence, and resets.

This module handles the application's stateful data that needs to persist across
Streamlit reruns, including course progress, UI state, and cached content.

Note: This is related to Streamlit's session state management (not a formal state machine).
Streamlit reruns the entire script on each interaction, so session_state maintains
data between reruns.
"""

import streamlit as st
from pathlib import Path

from src.core.tutor import SimpleTutor
from src.core.prompt_templates import DEFAULT_USER_PROMPTS
from src.config.constants import DEFAULT_TEST_COUNTS
from src.managers.cache_manager import load_cache_from_disk
from src.managers.prefetch_manager import cancel_and_reset

MASTERY_STATES = {
    'MASTERY_SETUP', 'MASTERY_TEST', 'MASTERY_FEEDBACK',
    'MASTERY_JOURNEY_CARD', 'MASTERY_JOURNEY_TEST', 'MASTERY_JOURNEY_DONE'
}

# --- STATE INITIALIZATION ---

def switch_course(filename):
    """
    Hard-switch to a different course with full memory wipe.
    Equivalent to ctrl+r but targeting a specific course.
    Clears all in-memory state before loading the new course.
    """
    cancel_and_reset()
    # Wipe in-memory content cache entirely (disk cache stays intact)
    st.session_state.content_cache = {}
    st.session_state.card_content = None
    st.session_state.questions = None
    st.session_state.future_questions = None
    st.session_state.answers = []
    st.session_state.tutor = None
    
    # Wipe mastery state (irrelevant cross-course)
    st.session_state.mastery_journey_active = False
    st.session_state.mastery_journey_queue = []
    st.session_state.mastery_journey_idx = 0
    st.session_state.mastery_selected = {}
    st.session_state.mastery_questions = []
    st.session_state.mastery_selected_ids = []
    
    # Load the new course fresh (restores its own saved progress from disk)
    load_course(filename)

def initialize_session_state():
    """
    Initialize all session state variables with their default values.
    
    This function sets up the initial state for:
    - API adapter
    - UI settings (show_settings)
    - Test configuration (test_counts, selected_models)
    - Custom prompts
    - Quick test mode
    - Content cache
    - Card and question data
    - Course progress tracking
    - Mastery Mode state
    
    Called automatically on app startup to ensure all required state exists.
    """
    # API Adapter
    if 'api_adapter' not in st.session_state:
        st.session_state.api_adapter = None
    
    # UI State
    if 'show_settings' not in st.session_state:
        st.session_state.show_settings = False
    
    # Test Configuration
    if 'test_counts' not in st.session_state:
        st.session_state.test_counts = DEFAULT_TEST_COUNTS.copy()
    
    if 'selected_models' not in st.session_state:
        st.session_state.selected_models = {}
    
    if 'custom_prompts' not in st.session_state:
        st.session_state.custom_prompts = DEFAULT_USER_PROMPTS.copy()
    
    # Quick Test Mode
    if 'is_quick_test' not in st.session_state:
        st.session_state.is_quick_test = False
    
    # Content Cache
    if 'content_cache' not in st.session_state:
        st.session_state.content_cache = {}
    
    # Card Content
    if 'card_content' not in st.session_state:
        st.session_state.card_content = None

    if 'balloons_shown' not in st.session_state:
        st.session_state.balloons_shown = False
    
    # Question Management
    if 'future_questions' not in st.session_state:
        st.session_state.future_questions = None

    if 'future_next_questions' not in st.session_state:
        st.session_state.future_next_questions = None
    
    if 'preloaded_next_card' not in st.session_state:
        st.session_state.preloaded_next_card = None
    
    if 'questions' not in st.session_state:
        st.session_state.questions = None
    
    if 'answers' not in st.session_state:
        st.session_state.answers = []
    
    if 'current_question_idx' not in st.session_state:
        st.session_state.current_question_idx = 0
    
    # Course Progress
    if 'passed_elements' not in st.session_state:
        st.session_state.passed_elements = set()

    if 'ignored_elements' not in st.session_state:
        st.session_state.ignored_elements = set()
    
    if 'force_test' not in st.session_state:
        st.session_state.force_test = False

    if 'raw_mode' not in st.session_state:
        st.session_state.raw_mode = False
    
    if 'current_course_path' not in st.session_state:
        st.session_state.current_course_path = None

    # -------------------------------------------------------------------------
    # MASTERY MODE STATE
    # -------------------------------------------------------------------------

    # Setup screen: which lessons the user has checked
    if 'mastery_selected' not in st.session_state:
        st.session_state.mastery_selected = {}

    # Questions used for the mastery range test (carries 'source' field per question)
    if 'mastery_questions' not in st.session_state:
        st.session_state.mastery_questions = []

    # Lesson IDs selected for the mastery test (for reference / re-launch)
    if 'mastery_selected_ids' not in st.session_state:
        st.session_state.mastery_selected_ids = []

    # Journey: ordered list of failed lesson IDs to revisit
    if 'mastery_journey_queue' not in st.session_state:
        st.session_state.mastery_journey_queue = []

    # Journey: current position in the queue
    if 'mastery_journey_idx' not in st.session_state:
        st.session_state.mastery_journey_idx = 0

    # Journey: True when a journey is in progress (survives state transitions)
    if 'mastery_journey_active' not in st.session_state:
        st.session_state.mastery_journey_active = False

# --- STATE RESET ---

def full_reset():
    """
    Reset all temporary content and test-related state variables.
    
    Clears:
    - Card content
    - Generated questions (questions, future_questions, future_next_questions)
    - Preloaded next card
    - User answers
    - Quick test mode flag
    - Balloons shown flag

    Does NOT clear mastery journey queue or journey progress, so the journey
    can survive navigation across lesson boundaries.
    
    This is typically called after completing a test or moving to a new lesson,
    ensuring clean state for the next content.
    """
    st.session_state.card_content = None
    st.session_state.questions = None
    st.session_state.preloaded_next_card = None
    st.session_state.answers = []
    st.session_state.is_quick_test = False
    st.session_state.balloons_shown = False
    st.session_state.future_next_questions = None
    st.session_state.future_questions = None
    st.session_state.pop('retry_questions', None)

    # Clear SRS guard flags so any re-visit or navigation records fresh results
    for key in [k for k in st.session_state
                if k.startswith('srs_recorded_') or k.startswith('srs_batch_recorded_')]:
        del st.session_state[key]

    # Note: mastery_journey_queue / mastery_journey_idx / mastery_journey_active
    # are intentionally NOT reset here – they persist across lesson transitions.


# --- STATE PERSISTENCE ---

def save_full_state():
    """
    Save complete course progress to disk.
    
    Persists:
    - Current position in course (current_id)
    - Tutor state (CARD, TEST, FEEDBACK)
    - Passed elements (completed lessons/concepts)
    
    Uses ProgressManager to write state to disk, allowing users to resume
    their progress in future sessions.
    
    Returns early if no tutor is loaded or no course is active.
    """
    if not st.session_state.tutor or not st.session_state.current_course_path:
        return
    
    course_filename = Path(st.session_state.current_course_path).name

    persisted_state = (
        'CARD'
        if st.session_state.tutor.state in MASTERY_STATES
        else st.session_state.tutor.state
    )

    state_dump = {
        'current_id': st.session_state.tutor.current_id,
        'tutor_state': persisted_state,
        'passed_elements': list(st.session_state.passed_elements),
        'ignored_elements': list(st.session_state.ignored_elements),
    }
    st.session_state.progress_manager.save(state_dump, course_filename)


def load_course(filename):
    """
    Load a course and restore its saved progress.
    
    Complete workflow:
    1. Load saved progress (position, passed elements)
    2. Apply progress to session
    3. Load cached content from disk
    4. Save course as "last active" in settings
    5. Reset temporary state
    
    Args:
        filename (str): Name of the course file (e.g., "python_basics.json")
        
    Returns:
        bool: True if course loaded successfully, False if file doesn't exist
        
    Side effects:
        - Updates session_state.tutor
        - Updates session_state.current_course_path
        - Updates session_state.passed_elements
        - Updates session_state.content_cache
        - Shows toast notifications for user feedback
    """
    from src.utils.settings_utils import save_all_settings

    full_path = Path("data/courses") / filename
    
    if not full_path.exists():
        return False
    
    # 1. Initialize tutor with course
    st.session_state.tutor = SimpleTutor(str(full_path))
    st.session_state.current_course_path = str(full_path)
    
    # 2. Load saved progress from disk
    saved_data = st.session_state.progress_manager.load(filename)
    
    # 3. Apply progress to session
    if saved_data:
        st.session_state.tutor.current_id = saved_data.get(
            'current_id', 
            st.session_state.tutor.current_id
        )
        st.session_state.tutor.state = saved_data.get('tutor_state', 'CARD')
        passed_list = saved_data.get('passed_elements', [])
        st.session_state.passed_elements = set(passed_list)
        ignored_list = saved_data.get('ignored_elements', [])
        st.session_state.ignored_elements = set(ignored_list)
        st.toast(f"Progress loaded — {len(passed_list)} lessons completed.", icon=":material/restore:")
    else:
        st.session_state.passed_elements = set()
        st.session_state.ignored_elements = set()
        st.toast(f"New course started: {filename}", icon=":material/fiber_new:")
    
    # 4. Load content cache
    if load_cache_from_disk(filename):
        count = len(st.session_state.content_cache.get(filename, {}))
        st.toast(f"Restored {count} cached lessons from disk.", icon=":material/memory:")
    else:
        if filename not in st.session_state.content_cache:
            st.session_state.content_cache[filename] = {}
    
    # 5. Save as "last active course" in global settings
    save_all_settings()
    
    # 6. Reset temporary state (including any leftover mastery state)
    full_reset()
    st.session_state.mastery_journey_active = False
    st.session_state.mastery_journey_queue = []
    st.session_state.mastery_journey_idx = 0
    st.session_state.mastery_selected = {}
    st.session_state.mastery_questions = []
    st.session_state.mastery_selected_ids = []
    
    return True