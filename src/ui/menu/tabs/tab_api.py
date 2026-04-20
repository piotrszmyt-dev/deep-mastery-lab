"""
API & AI Tab Renderer
=====================
Handles provider selection, API key entry, model assignment,
and the model library (add/remove/reset).

Architecture:
- Provider dropdown auto-builds from PROVIDERS_REGISTRY
- Model lists loaded from models_manager (JSON → fallback to factory defaults)
- Model library section mirrors the Teaching Styles preset UI pattern

Cloud deployment (Streamlit Community Cloud):
- Add IS_CLOUD = true to the app's Secrets (Settings → Secrets in the Cloud dashboard)
- This puts KeysManager in cloud_mode: save() becomes a no-op, load() returns {}
- Keys never touch the shared filesystem — each user's key lives only in their
  st.session_state for the duration of their session, preventing cross-user leakage
- Verified status is always session-scoped (st.session_state._verified_keys), both
  locally and on Cloud
"""

import streamlit as st

from pathlib import Path

from src.config.providers_registry import (
    PROVIDERS_REGISTRY,
    get_provider_keys,
    build_adapter,
)
from src.managers.models_manager import (
    get_models,
    get_model_display_names,
    add_model,
    remove_model,
    reset_provider_to_defaults,
    resolve_model_id
)

from src.utils.settings_utils import save_all_settings
from src.managers.cache_manager import clear_cards_cache, clear_questions_cache
from src.managers import srs_manager

# =============================================================================
# HELPERS FOR API KEYS MANAGEMENT AND TESTING
# =============================================================================

def _is_key_verified(provider: str) -> bool:
    """Check if the current key for this provider has been verified."""
    return provider in st.session_state.get('_verified_keys', set())

def _mark_key_verified(provider: str):
    """Mark this provider's key as verified. Persists to disk locally; no-op on cloud."""
    if '_verified_keys' not in st.session_state:
        st.session_state._verified_keys = set()
    st.session_state._verified_keys.add(provider)
    keys_data = st.session_state.keys_manager.load()
    verified = keys_data.get('_verified', [])
    if provider not in verified:
        verified.append(provider)
        keys_data['_verified'] = verified
        st.session_state.keys_manager.save(keys_data)

def _clear_key_verified(provider: str):
    """Remove verified status. Persists to disk locally; no-op on cloud."""
    if '_verified_keys' not in st.session_state:
        st.session_state._verified_keys = set()
    st.session_state._verified_keys.discard(provider)
    keys_data = st.session_state.keys_manager.load()
    verified = keys_data.get('_verified', [])
    if provider in verified:
        verified.remove(provider)
        keys_data['_verified'] = verified
        st.session_state.keys_manager.save(keys_data)

def _test_adapter_call(adapter, model_id: str) -> tuple[bool, str]:
    """
    Fires a minimal 1-token call to verify both adapter (key) and model ID are valid.
    Used for key verification on Connect, and model validation on Add.
    Returns (success, error_message).
    Error message is empty string on success.
    """
    try:
        result = adapter.generate("Hi", model=model_id, max_tokens=16)
        content = result.get('content') or ''
        if content.startswith('❌ Error:'):
            error_msg = content.replace('❌ Error:', '').strip()
            print(f"[_test_adapter_call] model={model_id} error={error_msg}")
            return False, error_msg
        return True, ''
    except Exception as e:
        print(f"[_test_adapter_call] model={model_id} exception={e}")
        return False, str(e)

# =============================================================================
# SESSION STATE BOOTSTRAP
# =============================================================================

def _init_session_state():
    """Initialises all required session state keys with safe defaults."""
    if "active_provider" not in st.session_state:
        st.session_state.active_provider = "openrouter"

    if "api_key" not in st.session_state:
        st.session_state.api_key = ''

    if "api_adapter" not in st.session_state:
        st.session_state.api_adapter = None

    if "_verified_keys" not in st.session_state:
        st.session_state._verified_keys = set()

    if "selected_models" not in st.session_state:
        _reset_model_selections(st.session_state.active_provider)

def _reset_model_selections(provider_key: str):
    """Sets selected_models to the first model in each slot for the given provider."""
    names = get_model_display_names(provider_key)
    default_name = names[0] if names else ""
    st.session_state.selected_models = {
        "presentation": default_name,
        "questions": default_name,
        "synthesis": default_name,
    }

# =============================================================================
# PROVIDER SWITCHING
# =============================================================================

def _switch_provider(new_provider_key: str):
    """
    Switches the active provider.
    Resets the adapter and model selections.
    Does NOT clear course cache — that's the user's choice via the popover.
    """
    st.session_state.active_provider = new_provider_key
    st.session_state.api_adapter = None  # always kill adapter on switch
    st.session_state.api_key = st.session_state.get('api_keys', {}).get(new_provider_key, '')
    _clear_key_verified(new_provider_key)

    _reset_model_selections(new_provider_key)
    saved = st.session_state.get('all_selected_models', {})
    if new_provider_key in saved:
        st.session_state.selected_models = saved[new_provider_key]

def _build_adapter_from_state() -> bool:
    """
    Tries to instantiate the adapter from current session state.
    Returns True if successful.
    """
    provider = st.session_state.active_provider
    key = st.session_state.api_key

    if not key or not key.strip():
        return False

    adapter = build_adapter(provider, key.strip())
    if adapter:
        st.session_state.api_adapter = adapter
        # Save key to keys.json
        if 'api_keys' not in st.session_state:
            st.session_state.api_keys = {}
        st.session_state.api_keys[provider] = key
        st.session_state.keys_manager.save(st.session_state.api_keys)
        return True
    return False   

# =============================================================================
# UI SECTIONS
# =============================================================================

def _render_provider_section():
    """Provider dropdown + lock warning + description card."""
    st.markdown("#### :material/hub: API Provider")

    provider_keys = get_provider_keys()
    provider_names = [
        f"{v['display_name']} — {v['badge']}" if v.get('badge') else v['display_name']
        for v in PROVIDERS_REGISTRY.values()
    ]
    current_key = st.session_state.active_provider
    current_index = provider_keys.index(current_key) if current_key in provider_keys else 0

    # Provider selector
    selected_name = st.selectbox(
        "Active Provider",
        options=provider_names,
        index=current_index,
        key="provider_selectbox",
    )

    # Map back to key
    selected_key = provider_keys[provider_names.index(selected_name)]

    # Handle switch
    if selected_key != current_key:
        _switch_provider(selected_key)
        save_all_settings() 
        st.rerun()

def _render_api_key_section():
    """
    API key input with 4-state status label and deferred connection test.
    On Connect: arms the adapter then sets _connection_testing flag.
    Next render pass runs the test call and marks the key verified or clears the adapter.
    """
    provider = st.session_state.active_provider
    entry = PROVIDERS_REGISTRY[provider]
    is_connected = bool(st.session_state.api_adapter)
    is_verified = _is_key_verified(provider)

    # --- 4-state label (single place, stable layout) ---
    if st.session_state.get('_connection_testing'):
        key_label = "🔵 Testing connection..."
    elif is_connected and is_verified:
        key_label = "🟢 Connected and verified"
    elif st.session_state.get('_connection_error'):
        key_label = f"🟡 Invalid key — {st.session_state.pop('_connection_error')}"
    elif st.session_state.api_key:
        key_label = "🔴 Not connected — press Connect to verify"
    else:
        key_label = f"🔴 Paste your {entry['display_name']} key and press Connect"

    # Deferred connection test: flag was set on previous pass by Connect button.
    # Runs here — before any widgets — so the label reflects the result on next rerun.
    if st.session_state.get('_connection_testing'):
        st.session_state._connection_testing = False
        model_names = get_model_display_names(provider)
        test_model = st.session_state.selected_models.get(
            'presentation', model_names[0] if model_names else None
        )
        model_id = resolve_model_id(provider, test_model)
        ok, err = _test_adapter_call(st.session_state.api_adapter, model_id)
        if ok:
            _mark_key_verified(provider)
        else:
            st.session_state.api_adapter = None
            st.session_state._connection_error = err
        st.rerun()

    # --- Key input + button ---
    col_key, col_btn = st.columns([4, 1], vertical_alignment="bottom")

    with col_key:
        def _try_auto_connect():
            key_val = st.session_state[f"key_input_{provider}"]
            st.session_state.api_key = key_val
            st.session_state.api_adapter = None
            _clear_key_verified(provider)

        key_val = st.text_input(
            key_label,
            value=st.session_state.api_key,
            type="password",
            placeholder=entry["key_placeholder"],
            key=f"key_input_{provider}",
            on_change=_try_auto_connect,
        )

    if key_val != st.session_state.api_key:
        st.session_state.api_key = key_val
        st.session_state.api_adapter = None
        _clear_key_verified(provider)

    with col_btn:
        is_cloud = st.session_state.get('is_cloud', False)
        if is_connected and is_verified:
            if st.button("Disconnect", icon=":material/link_off:",
                        use_container_width=True, key="disconnect_btn", disabled=is_cloud):
                st.session_state.api_adapter = None
                _clear_key_verified(provider)
                st.rerun()
        elif st.session_state.api_key:
            if st.button("Connect", icon=":material/link:",
                        use_container_width=True, key="connect_btn", disabled=is_cloud):
                if _build_adapter_from_state():
                    # Set flag — actual test runs at top of next pass
                    st.session_state._connection_testing = True
                st.rerun()
        else:
            st.button("Connect", icon=":material/link:",
                     use_container_width=True, key="connect_btn", disabled=True)


def _render_model_assignment_section():
    """Three model selectors (Lesson / Question / Synthesis) in a 3-column row."""
    provider = st.session_state.active_provider
    st.markdown("#### :material/smart_toy: Model Assignment")

    model_names = get_model_display_names(provider)

    if not model_names:
        st.info("No models configured for this provider. Add some in the Model Library below.")
        return

    component_config = [
        ("presentation", "Lesson", ":material/menu_book:",
         "Used for main lesson content generation."),
        ("questions",    "Questions", ":material/quiz:",
         "Used for quiz and question generation."),
        ("synthesis",    "Summary", ":material/auto_awesome:",
         "Used for summaries and synthesis."),
    ]

    def _sync_and_save():
        """Reads current widget values into selected_models then saves."""
        provider = st.session_state.active_provider
        for k in ["presentation", "questions", "synthesis"]:
            widget_key = f"model_sel_{k}_{provider}"
            if widget_key in st.session_state:
                st.session_state.selected_models[k] = st.session_state[widget_key]
        if 'all_selected_models' not in st.session_state:
            st.session_state.all_selected_models = {}
        st.session_state.all_selected_models[provider] = st.session_state.selected_models
        save_all_settings()

    cols = st.columns(3)

    for col, (key, label, icon, description) in zip(cols, component_config):
        with col:
            current = st.session_state.selected_models.get(key, model_names[0])
            current_index = model_names.index(current) if current in model_names else 0

            selected_name = st.selectbox(
                f"{icon} {label}",
                options=model_names,
                index=current_index,
                key=f"model_sel_{key}_{provider}",
                help=description,
                on_change=_sync_and_save,
            )

            st.session_state.selected_models[key] = selected_name
            if 'all_selected_models' not in st.session_state:
                st.session_state.all_selected_models = {}
            st.session_state.all_selected_models[provider] = st.session_state.selected_models

    with st.popover("Clear Cache", icon=":material/autorenew:", use_container_width=True,
                    disabled=st.session_state.get('is_cloud', False)):
        st.markdown("##### :material/warning: Reset Course Data?")
        st.warning("These actions are irreversible.")

        course_path = st.session_state.get('current_course_path')
        course_filename = Path(course_path).name if course_path else st.session_state.get('last_active_course') or None

        st.markdown("**Cache**")
        col_cards, col_q = st.columns(2)
        with col_cards:
            if st.button("Clear Cards", icon=":material/menu_book:", use_container_width=True,
                         key="clear_cards_btn", disabled=not course_filename):
                if course_filename and clear_cards_cache(course_filename):
                    st.toast("Lesson cards cleared.", icon=":material/check_circle:")
                    st.rerun()
                else:
                    st.error("No cards cache found.")
        with col_q:
            if st.button("Clear Questions", icon=":material/quiz:", use_container_width=True,
                         key="clear_questions_btn", disabled=not course_filename):
                if course_filename and clear_questions_cache(course_filename):
                    srs_manager.reset_srs(course_filename)
                    st.toast("Question pools and SRS progress cleared.", icon=":material/check_circle:")
                    st.rerun()
                else:
                    st.error("No question cache found.")
        st.caption("⚠️ Clearing Questions also resets SRS review progress for this course.")




def _render_model_library_section():
    """
    Model library — mirrors Teaching Styles preset pattern.
    Selectbox of all models for the active provider, with Add / Delete / Factory Reset.
    """
    provider = st.session_state.active_provider
    st.markdown("#### :material/library_books: Model Library")
    if st.session_state.get('_model_added_msg'):
        st.success(f"{st.session_state.pop('_model_added_msg')}")
    with st.container(border=True):
        models = get_models(provider)
        model_names = [m["display_name"] for m in models]

        if not model_names:
            st.info("No models. Add one below.")
            model_names = []
            selected_lib_name = None
        else:
            col_sel, col_add, col_del = st.columns([3, 1, 1], vertical_alignment="bottom")

            with col_sel:
                selected_lib_name = st.selectbox(
                    "Model",
                    options=model_names,
                    key=f"lib_model_sel_{provider}",
                    help="Select a model to inspect or delete.",
                    label_visibility="collapsed",
                )

            # --- ADD ---
            is_verified = _is_key_verified(st.session_state.active_provider)

            with col_add:
                with st.popover("Add", icon=":material/add_circle:",
                                use_container_width=True,
                                disabled=not is_verified):  # ← disabled if not verified
                    if not is_verified:
                        st.info("Connect and verify an API key first.")
                    else:
                        st.markdown("##### Add Model")
                        new_display = st.text_input(
                            "Display Name",
                            placeholder="e.g. My GPT-4o",
                            key=f"new_display_{provider}",
                        )
                        new_id = st.text_input(
                            "Model ID",
                            placeholder="e.g. gpt-4o or openai/gpt-4o",
                            key=f"new_id_{provider}",
                        )

                        if st.button(
                            "Save Model",
                            icon=":material/save:",
                            type="primary",
                            use_container_width=True,
                            key=f"save_model_btn_{provider}",
                        ):
                            with st.spinner("Testing model ID..."):
                                model_id = resolve_model_id(
                                    st.session_state.active_provider, new_id
                                )
                                ok, err = _test_adapter_call(
                                    st.session_state.api_adapter, model_id
                                )
                            if ok:
                                entry = {
                                    "display_name": new_display,
                                    "model_id": new_id,
                                    "cost_input": 0.0,
                                    "cost_output": 0.0,
                                    "context_k": 0,
                                    "notes": "",
                                }
                                success, msg = add_model(provider, entry)
                                if success:
                                    st.session_state._model_added_msg = msg
                                    st.rerun()
                                else:
                                    st.error(msg)
                            else:
                                st.error(f"Invalid model ID: {err}")

            # --- DELETE ---
            with col_del:
                with st.popover(
                    "Delete",
                    icon=":material/delete:",
                    use_container_width=True,
                    disabled=st.session_state.get('is_cloud', False),
                ):
                    st.markdown(f"##### Remove **{selected_lib_name}**?")
                    st.warning("This removes the model from the list. No API calls are made.", icon=":material/warning:")

                    if st.button(
                        "Confirm Delete",
                        type="primary",
                        icon=":material/delete_forever:",
                        use_container_width=True,
                        key=f"confirm_del_{provider}",
                    ):
                        success, msg = remove_model(provider, selected_lib_name)
                        if success:
                            _reset_model_selections(provider)
                            st.toast(msg, icon="🗑️")
                            st.rerun()
                        else:
                            st.error(msg)

        # --- FACTORY RESET ---

        with st.popover(
            "Factory Reset",
            icon=":material/restart_alt:",
            use_container_width=True,
        ):
            st.markdown("##### Reset Model Library?")
            st.warning(
                "This restores the factory default model list for this provider. "
                "Your custom models will be removed.",
                icon=":material/warning:"
            )
            if st.button(
                "Confirm Reset",
                type="primary",
                icon=":material/delete_forever:",
                use_container_width=True,
                key=f"factory_reset_btn_{provider}",
            ):
                success, msg = reset_provider_to_defaults(provider)
                if success:
                    _reset_model_selections(provider)
                    st.toast(msg, icon="🔄")
                    st.rerun()
                else:
                    st.error(msg)
        
# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def render_api_tab():
    """
    Main render function for the API & AI configuration tab.
    Call this from your tab router.
    """
    _init_session_state()

    if st.session_state.get('is_cloud', False):
        st.info("API configuration is not available in the presentation demo.", icon=":material/info:")

    _render_provider_section()

    _render_api_key_section()
    st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)

    _render_model_assignment_section()

    _render_model_library_section()
