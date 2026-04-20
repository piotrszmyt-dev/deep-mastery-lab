"""
Models Manager
==============
Manages per-provider model lists as user preferences.

Design principles:
- No file I/O of its own. All persistence goes through save_all_settings()
  which writes to data/settings.json via SettingsManager.
- Works entirely with st.session_state.custom_models (a dict of provider_key → [model_list])
- Factory defaults live in providers_registry.py and are never modified.
- A provider entry only exists in custom_models if the user has changed something.
  If missing → get_models() falls back to factory defaults transparently.
- resolve_model_id() converts display names to model_id strings for API calls.
  This decouples UI selection (human-readable names) from API calls (model IDs).

Session state keys used:
    st.session_state.custom_models : dict
        {
            "openrouter": [ {display_name, model_id, cost_input, ...}, ... ],
            "openai":     [ ... ],
        }
        Only providers with user customizations appear here.
        Missing provider → use factory defaults from providers_registry.

Load path (call once at startup, e.g. in your main app init):
    settings = settings_manager.load()
    st.session_state.custom_models = settings.get("custom_models", {})
    st.session_state.active_provider = settings.get("active_provider", "openrouter")
"""

import streamlit as st
from typing import Optional

from src.config.providers_registry import get_default_models


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _get_custom_models() -> dict:
    """Returns the custom_models dict from session state, initialising if absent."""
    if "custom_models" not in st.session_state:
        st.session_state.custom_models = {}
    return st.session_state.custom_models

def _validate_model_entry(entry: dict) -> tuple[bool, str]:
    """Validates a model entry. Returns (is_valid, error_message)."""
    for field in ["display_name", "model_id"]:
        if not str(entry.get(field, "")).strip():
            return False, f"'{field}' is required and cannot be empty."
    return True, ""

def _normalize_entry(entry: dict) -> dict:
    """Normalizes all fields to their expected types and fills missing optional fields with safe defaults."""
    return {
        "display_name": str(entry.get("display_name", "")).strip(),
        "model_id":     str(entry.get("model_id", "")).strip(),
    }

def _save(save_fn=None):
    """
    Persists current session state via save_all_settings().
    Imported lazily to avoid circular imports.
    """
    if save_fn:
        save_fn()
        return
    try:
        from src.utils.settings_utils import save_all_settings
        save_all_settings()
    except Exception as e:
        print(f"[WARN] models_manager: could not persist settings: {e}")

# =============================================================================
# PUBLIC READ API
# =============================================================================

def resolve_model_id(provider_key: str, display_name: str) -> str:
    """Resolves a display name to its model_id. Falls back to display_name if not found."""
    
    models = get_models(provider_key)
    
    for m in models:
        if m['display_name'] == display_name:
            return m['model_id']
    
    return display_name

def get_models(provider_key: str) -> list[dict]:
    """
    Returns the model list for a provider.

    Priority:
        1. User-customized list from st.session_state.custom_models
        2. Factory defaults from providers_registry.py
    """
    custom = _get_custom_models()

    if provider_key in custom:
        return [_normalize_entry(m) for m in custom[provider_key]]

    return [_normalize_entry(m) for m in get_default_models(provider_key)]


def get_model_display_names(provider_key: str) -> list[str]:
    """Returns display names only — for use in st.selectbox options."""
    return [m["display_name"] for m in get_models(provider_key)]


def get_model_by_display_name(provider_key: str, display_name: str) -> Optional[dict]:
    """Finds a model entry by its display name. Returns None if not found."""
    for model in get_models(provider_key):
        if model["display_name"] == display_name:
            return model
    return None


def get_model_by_id(provider_key: str, model_id: str) -> Optional[dict]:
    """Finds a model entry by its model_id. Returns None if not found."""
    for model in get_models(provider_key):
        if model["model_id"] == model_id:
            return model
    return None


def is_using_defaults(provider_key: str) -> bool:
    """Returns True if no user customization exists for this provider."""
    return provider_key not in _get_custom_models()

# =============================================================================
# PUBLIC WRITE API
# All mutating functions modify session state then immediately save to disk.
# =============================================================================

def add_model(provider_key: str, entry: dict, save_fn=None) -> tuple[bool, str]:
    """
    Adds a new model to a provider's list and saves.

    Validates and normalizes the entry before adding. Rejects duplicates
    by both display_name and model_id. If the provider has no customizations
    yet, the factory defaults are loaded first so existing models are preserved.

    Args:
        provider_key: Provider identifier, e.g. "openrouter"
        entry:        Model dict with at least display_name and model_id.
                      Optional fields: cost_input, cost_output, context_k, notes.
        save_fn:      Optional save callback. If None, falls back to save_all_settings().

    Returns:
        (True,  "'<name>' added.")           on success
        (False, "<reason>")                  on validation failure or duplicate
    """
    is_valid, error = _validate_model_entry(entry)
    if not is_valid:
        return False, error

    current_models = get_models(provider_key)
    new_name = entry["display_name"].strip()
    new_id   = entry["model_id"].strip()

    for m in current_models:
        if m["display_name"] == new_name:
            return False, f"A model named '{new_name}' already exists."
        if m["model_id"] == new_id:
            return False, f"Model ID '{new_id}' is already in the list."

    current_models.append(_normalize_entry(entry))
    _get_custom_models()[provider_key] = current_models
    _save(save_fn)

    return True, f"'{new_name}' added."

def remove_model(provider_key: str, display_name: str, save_fn=None) -> tuple[bool, str]:
    """
    Removes a model by display name and saves.

    Returns:
        (success: bool, message: str)
    """
    current_models = get_models(provider_key)
    filtered = [m for m in current_models if m["display_name"] != display_name]

    if len(filtered) == len(current_models):
        return False, f"Model '{display_name}' not found."

    _get_custom_models()[provider_key] = filtered
    _save(save_fn)

    return True, f"'{display_name}' removed."

def reset_provider_to_defaults(provider_key: str, save_fn=None) -> tuple[bool, str]:
    """
    Removes user customizations for one provider, restoring factory defaults.
    Does NOT affect other providers.

    Returns:
        (success: bool, message: str)
    """
    custom = _get_custom_models()

    if provider_key not in custom:
        return True, "Already using factory defaults."

    del custom[provider_key]
    _save(save_fn)

    return True, f"'{provider_key}' models reset to factory defaults."


def reset_all_to_defaults(save_fn=None) -> tuple[bool, str]:
    """
    Clears all provider customizations, restoring factory defaults for everyone.

    Returns:
        (success: bool, message: str)
    """
    st.session_state.custom_models = {}
    _save(save_fn)

    return True, "All providers reset to factory defaults."