"""
Settings Utilities
==================
Central save/load utilities for global application settings.

Imported by any module that needs to persist settings:
- settings_menu_render.py
- sidebar_render.py
- tab_prompts.py
- tab_api.py
- tab_themes.py
- models_manager.py  ← calls save_all_settings() after every model list change

Managed keys (written by save_all_settings):
    custom_language     : str
    active_preset_name  : str
    prompt_presets      : dict
    custom_prompts      : dict
    selected_models     : dict  — which model is active for lesson/questions/synthesis
    test_counts         : dict
    active_theme_name   : str
    active_provider     : str  — which API provider is selected (openrouter/openai/...)
    custom_models       : dict — per-provider user model lists (empty = use factory defaults)

Unmanaged keys (owned by other modules, preserved on every save):
    hidden_courses          : list  — managed by srs_render._save_hidden_courses
    course_display_names    : dict  — managed by srs_render._save_display_names
"""

from anyio import Path
from pathlib import Path

import streamlit as st
import copy

from src.core.prompt_templates import (
    DEFAULT_USER_PROMPTS,
    DEFAULT_PRESETS,
    DEFAULT_PRESET_NAME,
    get_full_prompts_from_preset,
)



def save_all_settings() -> bool:
    """
    Save all global settings to disk immediately.

    Single source of truth for settings persistence.
    Covers: language, presets, models, counts, theme,
            active provider, and user-customized model lists.

    Keys not managed here (hidden_courses, course_display_names, etc.) are
    preserved by merging with the existing file before writing.

    Returns:
        bool: True if save successful, False otherwise.
    """
    # Preserve keys owned by other modules (hidden_courses, course_display_names, …)
    try:
        existing = st.session_state.settings_manager.load()
    except Exception:
        existing = {}

    config = {
        **existing,  # carry over any unmanaged keys first
        # --- Existing keys (unchanged) ---
        'custom_language':    st.session_state.get('custom_language', 'English'),
        'active_preset_name': st.session_state.get('active_preset_name', ''),
        'prompt_presets':     st.session_state.get('prompt_presets', {}),
        'custom_prompts':     st.session_state.get('custom_prompts', {}),
        'test_counts':        st.session_state.get('test_counts', {}),
        'active_theme_name':  st.session_state.get('active_theme_name', ''),
        'lesson_context_window': st.session_state.get('lesson_context_window', 6),
        'lesson_max_questions': st.session_state.get('lesson_max_questions', 0),
        'raw_mode': st.session_state.get('raw_mode', False),

        # --- Model assignment (which model slot → which model name) ---
        # e.g. {"presentation": "DeepSeek Chat", "questions": "Claude, "synthesis": "DeepSeek Chat"}
        'selected_models': {
            **st.session_state.get('all_selected_models', {}),
            st.session_state.get('active_provider', 'openrouter'): st.session_state.get('selected_models', {})
        },

        # --- Provider & custom model lists ---
        # Active provider key, e.g. "openrouter", "openai", "anthropic"
        'active_provider':    st.session_state.get('active_provider', 'openrouter'),

        # Per-provider user-customized model lists.
        # Only providers the user has modified appear here.
        # Missing provider → models_manager falls back to factory defaults.
        'custom_models':      st.session_state.get('custom_models', {}),
        'last_active_course': Path(st.session_state.current_course_path).name
                              if st.session_state.get('current_course_path') else '',
    }
    return st.session_state.settings_manager.save(config)


def load_all_settings():
    """
    Restores all settings from disk into session state.

    Call this once during app initialization, after SettingsManager is created.
    Safe to call even if settings.json doesn't exist yet — all keys have defaults.

    Handles:
    - Language, theme, test counts
    - Preset migration (old single-prompt format → new presets format)
    - Active preset + custom_prompts sync
    - Provider, custom model lists, selected models (provider-scoped)
    - Fresh defaults when no settings.json exists yet
    """

    settings = st.session_state.settings_manager.load()

    if settings:
        # --- Language (first — other logic may depend on it) ---
        st.session_state.custom_language = settings.get('custom_language', 'English')

        # --- Preset migration ---
        # Old format: single 'custom_prompts' dict
        # New format: 'prompt_presets' dict + 'active_preset_name'
        if 'prompt_presets' not in settings:
            # Migrate old format
            old_prompts = settings.get('custom_prompts', {})
            st.session_state.prompt_presets = {
                DEFAULT_PRESET_NAME: {
                    'presentation': DEFAULT_USER_PROMPTS['presentation'],
                    'synthesis': DEFAULT_USER_PROMPTS['synthesis'],
                }
            }
            if old_prompts and any(old_prompts.get(k) for k in ['presentation', 'synthesis']):
                st.session_state.prompt_presets['My Custom Style'] = {
                    'presentation': old_prompts.get('presentation', DEFAULT_USER_PROMPTS['presentation']),
                    'synthesis': old_prompts.get('synthesis', DEFAULT_USER_PROMPTS['synthesis']),
                }
                st.session_state.active_preset_name = 'My Custom Style'
            else:
                st.session_state.active_preset_name = DEFAULT_PRESET_NAME
        else:
            # Load presets directly, then always refresh Factory Default from code
            st.session_state.prompt_presets = settings.get('prompt_presets', copy.deepcopy(DEFAULT_PRESETS))
            st.session_state.prompt_presets[DEFAULT_PRESET_NAME] = copy.deepcopy(DEFAULT_PRESETS[DEFAULT_PRESET_NAME])
            st.session_state.active_preset_name = settings.get('active_preset_name', DEFAULT_PRESET_NAME)
            # Guard against deleted preset still being active
            if st.session_state.active_preset_name not in st.session_state.prompt_presets:
                st.session_state.active_preset_name = DEFAULT_PRESET_NAME

        # --- Sync custom_prompts and text area keys from active preset ---
        active_preset = st.session_state.prompt_presets[st.session_state.active_preset_name]
        st.session_state.custom_prompts = get_full_prompts_from_preset(active_preset)
        st.session_state.txt_presentation = active_preset.get('presentation', '')
        st.session_state.txt_synthesis    = active_preset.get('synthesis', '')

        # --- Theme & counts ---
        st.session_state.active_theme_name = settings.get('active_theme_name', '')
        st.session_state.test_counts      = settings.get('test_counts', {})
        st.session_state.last_active_course = settings.get('last_active_course', '') 

        # --- Provider (must come before selected_models) ---
        st.session_state.active_provider = settings.get('active_provider', 'openrouter')
        st.session_state.custom_models   = settings.get('custom_models', {})

        # --- Load API keys (separate file, git-ignored) ---
        keys = st.session_state.keys_manager.load()
        st.session_state.api_keys = keys
        # Restore verified status from disk (always empty set on cloud, since load() returns {})
        st.session_state._verified_keys = set(keys.get('_verified', []))

        # --- context window ---
        st.session_state.lesson_context_window = settings.get('lesson_context_window', 6)
        st.session_state.lesson_max_questions  = settings.get('lesson_max_questions', 0)
        if st.session_state.get('is_cloud', False):
            st.session_state.raw_mode = False   # cloud demo: show AI content by default
        else:
            st.session_state.raw_mode = settings.get('raw_mode', True)  # local: raw mode by default



        # --- Auto-connect for active provider if key was previously verified ---
        # Only rebuilds the adapter when _verified confirms the key was tested.
        # Disconnect clears _verified from disk, so restarting after a disconnect
        # leaves the adapter None (System Offline) even if the key is still saved.
        from src.config.providers_registry import build_adapter
        active_key = keys.get(st.session_state.active_provider, '')
        was_verified = st.session_state.active_provider in keys.get('_verified', [])
        if active_key and was_verified:
            adapter = build_adapter(st.session_state.active_provider, active_key)
            st.session_state.api_adapter = adapter if adapter else None
        else:
            st.session_state.api_adapter = None
        st.session_state.api_key = active_key  # always restore key for display

        # --- Selected models (provider-scoped) ---
        if 'selected_models' in settings:
            all_models = settings['selected_models']
            st.session_state.all_selected_models = all_models
            st.session_state.selected_models = all_models.get(st.session_state.active_provider, {})

        st.toast("Settings loaded", icon=":material/settings:")

    else:
        # --- No settings.json yet — apply fresh defaults ---
        st.session_state.custom_language     = 'English'
        st.session_state.prompt_presets      = copy.deepcopy(DEFAULT_PRESETS)
        st.session_state.active_preset_name  = DEFAULT_PRESET_NAME
        st.session_state.custom_prompts      = copy.deepcopy(DEFAULT_USER_PROMPTS)
        st.session_state.active_theme_name   = ''
        st.session_state.last_active_course  = ''
        st.session_state.test_counts         = {}
        st.session_state.active_provider     = 'openrouter'
        st.session_state.custom_models       = {}
        st.session_state.all_selected_models = {}
        st.session_state.selected_models     = {}
        st.session_state.api_keys            = {}
        st.session_state.lesson_context_window = 6
        st.session_state.lesson_max_questions  = 0
        st.session_state.raw_mode            = False






    

    