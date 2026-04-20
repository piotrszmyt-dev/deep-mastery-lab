"""
Prompts Tab Renderer
====================
Manages AI instruction presets and generation language settings.

Features:
- Output language selector with per-course cache reset option
- Preset system for saving and switching teaching styles
- Text editors for Presentation and Synthesis prompts
- Factory Default preset is read-only; custom presets are fully editable
- Auto-saves on every prompt change and preset switch

Note:
    Question generation prompts are intentionally not exposed here —
    their quality directly determines course content quality.
"""

import streamlit as st

from pathlib import Path

from src.utils.settings_utils import save_all_settings
from src.core.prompt_templates import (
    DEFAULT_PRESETS,           
    DEFAULT_PRESET_NAME,       
    get_full_prompts_from_preset  
)
from src.managers.cache_manager import clear_cards_cache, clear_questions_cache
from src.managers import srs_manager

def update_active_preset():
    """Save changes to active preset immediately"""
    preset_name = st.session_state.active_preset_name
    
    # Presets only store presentation + synthesis (questions is hardcoded)
    st.session_state.prompt_presets[preset_name] = {
        'presentation': st.session_state.txt_presentation,
        'synthesis': st.session_state.txt_synthesis
    }
    
    # Update custom_prompts with all 3 keys
    st.session_state.custom_prompts = get_full_prompts_from_preset(
        st.session_state.prompt_presets[preset_name]
    )

    save_all_settings()

def delete_preset_callback():
    """Delete current preset (except Factory)"""
    
    name = st.session_state.active_preset_name
    if name == DEFAULT_PRESET_NAME:
        return
    
    del st.session_state.prompt_presets[name]
    st.session_state.active_preset_name = DEFAULT_PRESET_NAME
    
    factory_preset = st.session_state.prompt_presets[DEFAULT_PRESET_NAME]
    
    # Update custom_prompts with all 3 keys
    st.session_state.custom_prompts = get_full_prompts_from_preset(factory_preset)
    
    # Update text areas
    st.session_state.txt_presentation = factory_preset['presentation']
    st.session_state.txt_synthesis = factory_preset['synthesis']

    save_all_settings()
    
    st.toast(f"Deleted: {name}", icon=":material/delete:")
    st.rerun()

def render_prompts_tab():
    """Render the Prompts configuration tab."""
 
    # Input field reset flag: Streamlit doesn't allow direct widget value mutation
    # during a render pass. We set this flag after preset creation/collision so the
    # NEXT render pass clears the text input before any widget is drawn.
    # Must run before any widgets render — placing it at the top of the function
    # guarantees the injected empty value is in session_state when the widget initialises.
    if st.session_state.get('_clear_preset_input'):
        st.session_state.new_preset_name_input = ""
        st.session_state._clear_preset_input = False

    # Sync text area session keys from the authoritative preset data whenever the
    # active preset changes OR when Streamlit has cleaned up the widget keys.
    # Streamlit deletes widget-bound keys (txt_presentation / txt_synthesis) when
    # the text areas are not rendered (menu closed). On re-open the keys are gone
    # but _prompts_synced_for still matches, so we'd render empty fields.
    # The extra `not in st.session_state` guards catch that case.
    _sync_target = st.session_state.get('active_preset_name', DEFAULT_PRESET_NAME)
    if (st.session_state.get('_prompts_synced_for') != _sync_target
            or 'txt_presentation' not in st.session_state
            or 'txt_synthesis' not in st.session_state):
        _preset_data = st.session_state.get('prompt_presets', {}).get(_sync_target, {})
        st.session_state.txt_presentation = _preset_data.get('presentation', '')
        st.session_state.txt_synthesis    = _preset_data.get('synthesis', '')
        st.session_state._prompts_synced_for = _sync_target

    st.markdown("#### :material/language: Generation Language")
    # This ensures consistency across all generators without user messing with prompt text
    def save_language_callback():
        """Auto-save settings when language changes."""
        # Widget value is already in session_state at this point!
        new_lang = st.session_state.language_widget
        st.session_state.custom_language = new_lang

        if not save_all_settings():
            st.error("Save failed.", icon=":material/gpp_bad:")

    with st.container(border=False):
        col1, col2 = st.columns([3, 2], vertical_alignment="bottom")
        
        with col1:
            # 1. The Language Input
            st.text_input(
                "Output Language",
                value=st.session_state.get('custom_language', 'English'),
                key="language_widget",  
                placeholder="e.g., Chinese, German...",
                on_change=save_language_callback,
                help="The AI will use this language for all future content."
            )
                
        with col2:
            # 2. The Popover Button
            with st.popover("Apply to all content", icon=":material/autorenew:", use_container_width=True,
                            disabled=st.session_state.get('is_cloud', False)):
                st.markdown("##### :material/warning: Reset Course Data?")
                st.warning("This action is irreversible.")
                st.markdown("To apply changes to **existing** lessons, clear the cache below.")

                course_path = st.session_state.get('current_course_path')
                course_filename = Path(course_path).name if course_path else st.session_state.get('last_active_course') or None

                col_cards, col_q = st.columns(2)
                with col_cards:
                    if st.button("Clear Cards", icon=":material/menu_book:", use_container_width=True,
                                key="prompts_clear_cards_btn", disabled=not course_filename):
                        if course_filename and clear_cards_cache(course_filename):
                            st.toast("Cards cleared. Will regenerate with new data.", icon=":material/check_circle:")
                            st.rerun()
                        else:
                            st.error("No cards cache found.")
                with col_q:
                    if st.button("Clear Questions", icon=":material/quiz:", use_container_width=True,
                                key="prompts_clear_questions_btn", disabled=not course_filename):
                        if course_filename and clear_questions_cache(course_filename):
                            srs_manager.reset_srs(course_filename)
                            st.toast("Questions and SRS progress cleared. Will regenerate in new language.", icon=":material/check_circle:")
                            st.rerun()
                        else:
                            st.error("No question cache found.")
                st.caption("⚠️ Clearing Questions also resets SRS review progress for this course.")

    # ===== PROMPT EDITORS =====  

    # Initialize presets if not exists
    st.markdown("#### :material/smart_toy: Teaching Styles")
    with st.container(border=True):
        if 'prompt_presets' not in st.session_state:
            st.session_state.prompt_presets = DEFAULT_PRESETS.copy()
        if 'active_preset_name' not in st.session_state:
            st.session_state.active_preset_name = DEFAULT_PRESET_NAME

        col1, col2, col3 = st.columns([3, 1, 1], vertical_alignment="bottom")

        with col1:
            preset_names = list(st.session_state.prompt_presets.keys())
            selected = st.selectbox(
                "Active Preset",
                preset_names,
                index=preset_names.index(st.session_state.active_preset_name)
            )
            
            # Manual sync check (runs every render)
            if selected != st.session_state.active_preset_name:
                # User changed selection manually
                st.session_state.active_preset_name = selected
                preset = st.session_state.prompt_presets[selected]
                st.session_state.txt_presentation = preset['presentation']
                st.session_state.txt_synthesis = preset['synthesis']
                st.session_state.custom_prompts = get_full_prompts_from_preset(preset)
                save_all_settings()
                st.rerun()

        with col2:
            # Deferred execution: pick up the flag set by request_preset_creation()
            # during the previous render pass and execute the actual creation now,
            # when it's safe to call st.rerun().
            if st.session_state.get('_create_preset_requested'):
                new_name = st.session_state._create_preset_requested
                st.session_state._create_preset_requested = None  
                
                # Validate
                if new_name and new_name.strip():
                    if new_name not in st.session_state.prompt_presets:
                        # Save current work
                        update_active_preset()
                        
                        # Create new preset
                        factory = st.session_state.prompt_presets[DEFAULT_PRESET_NAME]
                        st.session_state.prompt_presets[new_name] = {
                            'presentation': factory['presentation'],
                            'synthesis': factory['synthesis']
                        }
                        
                        # Switch to it
                        st.session_state.active_preset_name = new_name
                        st.session_state.txt_presentation = factory['presentation']
                        st.session_state.txt_synthesis = factory['synthesis']
                        st.session_state.custom_prompts = get_full_prompts_from_preset(
                            st.session_state.prompt_presets[new_name]
                        )
                        
                        if 'new_preset_name_input' in st.session_state:
                            del st.session_state.new_preset_name_input
                        
                        st.session_state._clear_preset_input = True
                        # Save to disk
                        if save_all_settings():
                            st.toast(f"✨ Created '{new_name}'", icon="✨")
                        else:
                            st.error("Failed to save!")
                        
                        st.rerun() 
                    else:
                        st.session_state._clear_preset_input = True
                        st.error(f"'{new_name}' already exists!")
                        st.rerun()
                else:
                    st.error("Name cannot be empty!")
            
            with st.popover("New", icon=":material/add_circle:", use_container_width=True):
                def request_preset_creation():
                    # Deferred execution pattern: on_change callbacks fire during
                    # Streamlit's widget rendering phase. Calling st.rerun() here
                    # would interrupt rendering mid-pass and lose the widget value.
                    # Instead we store the name as a flag and let the NEXT full
                    # render pass (top of col2) pick it up and act on it safely.
                    new_name = st.session_state.new_preset_name_input
                    if new_name and new_name.strip():
                        st.session_state._create_preset_requested = new_name
                        st.session_state.new_preset_name_input = ""
                
                st.text_input(
                    "Preset Name", 
                    placeholder="Type and press Enter...",
                    key="new_preset_name_input",
                    on_change=request_preset_creation,
                    help="Press Enter to create"
                )

        with col3:
            # Delete button (disabled for Factory Default)
            is_factory = st.session_state.active_preset_name == DEFAULT_PRESET_NAME
            if st.button(
                "Delete", 
                icon=":material/delete:",
                disabled=is_factory,
                use_container_width=True,
                help="Cannot delete Factory Default"
            ):
                delete_preset_callback()  

        is_factory_active = st.session_state.active_preset_name == DEFAULT_PRESET_NAME
        _active_preset = st.session_state.prompt_presets.get(st.session_state.active_preset_name, {})

        # 1. Lesson Prompt
        col1, col2 = st.columns(2)

        # Column 1: Lesson Prompt
        with col1:
            st.session_state.custom_prompts['presentation'] = st.text_area(
                "Lesson Prompt",
                value=_active_preset.get('presentation', ''),
                height=400,
                on_change=update_active_preset,
                key="txt_presentation",
                disabled=is_factory_active,
                help="Factory Default is read-only. Create a new preset to customize." if is_factory_active else None
            )

        # Column 2: Summary Prompt
        with col2:
            st.session_state.custom_prompts['synthesis'] = st.text_area(
                "Summary Prompt",
                value=_active_preset.get('synthesis', ''),
                height=400,
                on_change=update_active_preset,
                key="txt_synthesis",
                disabled=is_factory_active,
                help="Factory Default is read-only. Create a new preset to customize." if is_factory_active else None
            )
    
    