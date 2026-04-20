"""
CARD State Renderer
===================
Complete rendering logic for the CARD state - the main lesson view.

This module handles:
- Lesson header with title and action buttons
- Content loading and display (stream, cache, or raw mode)
- Background question pool generation
- Test initiation action bar
- Final test congratulations card (special entry path)

Flow (normal lesson):
1. Header renders with action buttons and lesson title
2. Content loads from cache/preload or streams from API
3. Question pool generates in background while user reads
4. User clicks VERIFY MASTERY → test starts immediately
"""

import json
import os
import streamlit as st
import tempfile
from pathlib import Path

# --- Core ---
from src.core.generators import (
    generate_questions_background,
    generate_final_card,
    get_raw_context_data,
    build_lesson_source,
)
from src.core.prompt_templates import build_final_prompt

# --- API ---
from src.api.streaming import handle_stream_response
from src.api.usage_tracking import update_course_metrics

# --- Managers ---
from src.managers.cache_manager import (
    save_cache_to_disk,
    remove_card_cache,
    get_questions_for_test,
    get_questions_for_range,
    get_pool,
    clear_pool,
)
from src.managers.prefetch_manager import (
    run_prefetch_pipeline,
    load_card_from_disk,
    save_card_to_disk,
    reset_at_module_boundary,
)
from src.managers.state_manager import save_full_state, full_reset
from src.managers.models_manager import resolve_model_id
from src.utils.settings_utils import save_all_settings

# --- UI ---
from src.ui.components.shared_components import (
    render_lesson_title,
    render_keyboard_hint,
    handle_skip,
    render_mark_previous_button,
)
from src.ui.components.media_render import _media_render, _media_add_popover

# =============================================================================
# Entry Point
# =============================================================================

def render_card_state(tutor, adapter, executor):
    """
    Render the complete CARD state view.
    
    This is the main lesson view where users read content and start tests.
    
    Flow:
    1. Display lesson header with title and action buttons
    2. Load/generate lesson content (from cache, preload, or stream)
    3. Display content with Markdown rendering
    4. Generate questions in background
    5. Show test initiation button
    
    Args:
        tutor: SimpleTutor instance with course state
        adapter: API adapter for content generation
        executor: ThreadPoolExecutor instance passed from app.py
    """
    current = tutor.get_current_element()

    # === FINAL TEST ===
    if current.get('type') == 'final_test':
        course_filename = Path(st.session_state.current_course_path).name
        _render_final_test_card(tutor, adapter, course_filename)
        return
    
    # === LESSON HEADER ===
    _render_card_header(tutor, current)
    
    # === CARD STATE LOGIC ===
    if tutor.state == 'CARD':
        _render_card_content(tutor, adapter, executor, current)

# =============================================================================
# Header
# =============================================================================

def _render_card_header(tutor, current):
    """
    Render the full CARD header action bar.

    Left side: content buttons (regenerate, source popover).
    Right side: ignore toggle, manage previous, skip.
    """
    _render_action_buttons(tutor)
    render_lesson_title(current.get('lesson_title', ''))

def _render_action_buttons(tutor):
    """
    Render the full CARD header action bar.

    Left side: content buttons (regenerate, source popover).
    Right side: ignore toggle, manage previous, skip.
    """
    curr_key = Path(st.session_state.current_course_path).name \
        if st.session_state.current_course_path else "unknown"
    
    left_col, spacer_col, right_col = st.columns([5, 2, 3])
    
    with left_col:
        _render_content_action_buttons(tutor, curr_key)
    
    with right_col:
        b5, b6, b7 = st.columns(3)
        with b5:
            is_ignored = tutor.current_id in st.session_state.get('ignored_elements', set())
            elem_type = tutor.get_current_element().get('type', 'lesson')
            is_ignorable = elem_type == 'lesson'
            if st.button(
                "",
                icon=":material/cancel:" if is_ignored else ":material/block:",
                help="Un-ignore this lesson" if is_ignored else "Ignore lesson",
                key="head_ignore",
                use_container_width=True,
                type="primary" if is_ignored else "secondary",
                disabled=not is_ignorable
            ):
                _handle_ignore_toggle(tutor)
        with b6:
            render_mark_previous_button(tutor)
        with b7:
            if st.button("", icon=":material/step_into:", help="Mark as passed & Skip",
                         key="head_skip", use_container_width=True):
                handle_skip(tutor)

def _render_content_action_buttons(tutor, curr_key):
    """Left-side content inspection buttons — usable in both CARD and mastery journey."""
    current = tutor.syllabus.get(tutor.current_id, {})
    is_raw = st.session_state.get('raw_mode', False)
    elem_type = current.get('type', 'lesson')
    is_synthesis = elem_type in ('module_synthesis', 'module_checkpoint')

    b1, b2, b3, b4, b5 = st.columns(5)

    with b1:
        # In raw mode, regenerate is disabled for regular lessons (no AI content)
        # but stays active for synthesis/checkpoint (they still need AI generation)
        no_adapter = not st.session_state.get('api_adapter')
        regen_disabled = (is_raw and not is_synthesis) or no_adapter
        regen_help = "No API connection" if no_adapter else "Regenerate content"
        if st.button("", icon=":material/auto_awesome:", help=regen_help,
                     key="head_regen", use_container_width=True, disabled=regen_disabled):
            _handle_regenerate(tutor, curr_key)

    with b2:
        new_mode_label = "Switch to Default mode" if is_raw else "Switch to Raw mode"
        if st.button("", icon=":material/switch_access:", help=new_mode_label,
                     key="head_switch_view", use_container_width=True,
                     disabled=is_synthesis):
            st.session_state.raw_mode = not is_raw
            save_all_settings()
            st.rerun()

    with b3:
        if is_synthesis:
            st.button("", icon=":material/description:", help="Not available for this element type",
                      use_container_width=True, disabled=True)
        elif is_raw:
            # Raw mode shows source — popover shows AI content instead (if generated)
            ai_content = st.session_state.content_cache.get(curr_key, {}).get(tutor.current_id)
            if ai_content:
                with st.popover("", icon=":material/description:",
                                help="Show AI-generated content", use_container_width=True):
                    st.markdown(ai_content)
                    _media_render(curr_key, tutor.current_id, key_prefix="popover")
            else:
                st.button("", icon=":material/description:", help="No AI content generated yet",
                          use_container_width=True, disabled=True)
        else:
            with st.popover("", icon=":material/description:",
                            help="Show source material", use_container_width=True):
                source = current.get('lesson_source', '')
                st.markdown(source) if source else st.info("No source data available.")
                _media_render(curr_key, tutor.current_id, key_prefix="popover")

    with b4:
        pid = current.get('source_ids', [''])[0] if not is_synthesis else ''
        if not pid:
            st.button("", icon=":material/edit:", help="Not available for this element type",
                      use_container_width=True, disabled=True)
        else:
            with st.popover("", icon=":material/edit:",
                            help="Edit source text", use_container_width=True):
                st.caption(
                    "You are editing the **source paragraph** — the ground truth this lesson "
                    "is built from. Saving will update the course file and automatically "
                    "regenerate the AI card and question pool."
                )
                raw_text = tutor.syllabus.get('_master_index', {}).get(pid, '')
                edited = st.text_area("Source paragraph", value=raw_text, height=250,
                                      key=f"edit_src_{tutor.current_id}")
                if st.button("Save & Regenerate", key=f"save_src_{tutor.current_id}",
                             type="primary", use_container_width=True,
                             disabled=(edited.strip() == raw_text.strip())):
                    _handle_source_edit(tutor, curr_key, pid, edited)

    with b5:
        course_filename = Path(st.session_state.current_course_path).name \
            if st.session_state.current_course_path else None
        if not course_filename or is_synthesis:
            st.button("", icon=":material/attach_file:",
                      help="Not available for this element type",
                      use_container_width=True, disabled=True)
        else:
            with st.popover("", icon=":material/attach_file:",
                            help="Add media attachment", use_container_width=True):
                _media_add_popover(course_filename, tutor.current_id)


def _handle_source_edit(tutor, course_key, pid, new_text):
    """Update _master_index, re-derive lesson_source, clear caches, save course to disk."""
    new_text = new_text.strip()

    # Update in-memory syllabus
    tutor.syllabus['_master_index'][pid] = new_text
    elem = tutor.syllabus[tutor.current_id]
    elem['lesson_source'] = build_lesson_source(elem, tutor.syllabus['_master_index'])

    # Atomic write of course JSON
    course_path = st.session_state.current_course_path
    fd, tmp_path = tempfile.mkstemp(dir=str(Path(course_path).parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(tutor.syllabus, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, course_path)
    except Exception:
        os.unlink(tmp_path)
        raise

    # Clear card and question caches for this lesson
    st.session_state.content_cache.get(course_key, {}).pop(tutor.current_id, None)
    save_cache_to_disk(course_key)
    clear_pool(course_key, tutor.current_id)

    # Reset render state and trigger regeneration
    st.session_state.card_content = None
    st.session_state.questions = None
    st.session_state.future_questions = None
    st.session_state._journey_regenerating = True

    st.toast("Source updated — card and questions will regenerate.", icon=":material/edit:")
    st.rerun()


def _handle_regenerate(tutor, course_key):
    """Clear cache and force content regeneration."""
    # remove_card_cache deletes from both memory and disk under the write lock.
    # save_cache_to_disk cannot be used here — it merges from disk first and
    # would resurrect the just-deleted entry.
    remove_card_cache(course_key, tutor.current_id)
    st.session_state.card_content = None
    st.session_state.future_questions = None
    st.session_state.questions = None
    st.session_state._journey_regenerating = True
    st.rerun()

def _handle_ignore_toggle(tutor):
    """Toggle ignored state and move to next if ignoring."""
    eid = tutor.current_id
    if eid in st.session_state.ignored_elements:
        # Un-ignore: restore to not-passed state
        st.session_state.ignored_elements.discard(eid)
        save_full_state()
        st.rerun()
    else:
        # Ignore: remove from passed, add to ignored, advance
        st.session_state.ignored_elements.add(eid)
        st.session_state.passed_elements.discard(eid)
        tutor.move_to_next()
        save_full_state()
        full_reset()
        st.rerun()

# =============================================================================
# Content
# =============================================================================

def _render_card_content(tutor, adapter, executor, current):
    """
    Main content rendering logic for CARD state.
    
    Handles:
    - Cache setup
    - Content loading (cache/preload/generate)
    - Content display
    - Background question generation
    - Action bar with test button
    """
    # 1. SETUP: Cache keys
    if st.session_state.current_course_path:
        current_course_key = Path(st.session_state.current_course_path).name
    else:
        current_course_key = "unknown_course"
    
    if current_course_key not in st.session_state.content_cache:
        st.session_state.content_cache[current_course_key] = {}
    
    # 2. GET CONTENT (cache → preload → generate)
    elem_type = current.get('type', 'lesson')
    is_synthesis_type = elem_type in ('module_synthesis', 'module_checkpoint')

    # Reset prefetch state once per module boundary to clear any hung threads
    boundary_key = f'_boundary_reset_{tutor.current_id}'
    if is_synthesis_type and not st.session_state.get(boundary_key):
        reset_at_module_boundary()
        st.session_state[boundary_key] = True

    if st.session_state.get('raw_mode') and not is_synthesis_type:
        _render_raw_card(tutor, current_course_key)
        _start_question_pool_generation(tutor, adapter, executor, current_course_key)
    else:
        content_to_show = _get_lesson_content(tutor, adapter, current_course_key)
        _display_lesson_content(content_to_show)
        content_to_show = content_to_show or st.session_state.card_content
        _start_question_pool_generation(tutor, adapter, executor, current_course_key)

    # 3. PREFETCH — runs in both modes, raw_mode flag controls card vs questions-only
    run_prefetch_pipeline(
        tutor, adapter, executor, current_course_key,
        st.session_state.selected_models,
        st.session_state.active_provider,
        st.session_state.custom_prompts,
        context_window=st.session_state.get('lesson_context_window', 3),
        raw_mode=st.session_state.get('raw_mode', False)
    )
    
    # Action bar always renders
    _render_action_bar(tutor, adapter, None, current_course_key)

def _render_raw_card(tutor, current_course_key):
    """Raw mode: lesson_source for regular lessons; cached AI content for synthesis/checkpoint."""
    current = tutor.get_current_element()
    elem_type = current.get('type', 'lesson')
    is_synthesis_type = elem_type in ('module_synthesis', 'module_checkpoint')

    with st.container(border=False, key="lesson_window"):
        if is_synthesis_type:
            # No lesson_source exists — show cached AI summary if prefetched
            cached = st.session_state.content_cache.get(current_course_key, {}).get(tutor.current_id)
            if not cached:
                cached = load_card_from_disk(current_course_key, tutor.current_id)
                if cached:
                    st.session_state.content_cache.setdefault(current_course_key, {})[tutor.current_id] = cached
            if cached:
                st.markdown(cached, unsafe_allow_html=True)
            else:
                st.warning("No summary available yet. Click **regenerate** to generate one.")
        else:
            raw_content = current.get('lesson_source', '')
            if raw_content:
                st.markdown(raw_content)
            else:
                st.warning("No raw content available for this lesson.")
            _media_render(current_course_key, tutor.current_id)

def _get_lesson_content(tutor, adapter, current_course_key):
    """
    Get or generate lesson content.
    
    Priority:
    1. Session state (already loaded)
    2. Cache (previously generated)
    3. Preload (background generated)
    4. Generate (stream with spinner)
    """
    content_to_show = st.session_state.card_content
    
    # Try cache
    if not content_to_show and tutor.current_id in st.session_state.content_cache[current_course_key]:
        cached = st.session_state.content_cache[current_course_key][tutor.current_id]
        if cached and "❌ Error" not in cached:
            content_to_show = cached
            st.session_state.card_content = content_to_show
    
    # Try preload
    if not content_to_show and not st.session_state.is_quick_test:
        preloaded = st.session_state.preloaded_next_card
        if not preloaded:
            preloaded = load_card_from_disk(current_course_key, tutor.current_id)
        if preloaded:
            content_to_show = preloaded
            st.session_state.preloaded_next_card = None
            st.session_state.card_content = content_to_show
            st.session_state.content_cache[current_course_key][tutor.current_id] = content_to_show
            save_cache_to_disk(current_course_key)
    
    return content_to_show

def _display_lesson_content(content_to_show):
    """
    Render lesson content inside the lesson_window container.

    If content_to_show is None, falls through to _generate_lesson_content
    which streams from the API. If content exists (cache or preload),
    renders it directly — streaming already handled display on generation.
    """
    card_window = st.container(border=False, key="lesson_window")
    
    with card_window:
        # Generate if needed
        if not content_to_show:
            content_to_show = _generate_lesson_content()
        else:
            st.markdown(content_to_show, unsafe_allow_html=True)

        tutor = st.session_state.get('tutor')
        if tutor and st.session_state.get('current_course_path'):
            elem = tutor.syllabus.get(tutor.current_id, {})
            if elem.get('type', 'lesson') not in ('module_synthesis', 'module_checkpoint'):
                _media_render(
                    Path(st.session_state.current_course_path).name,
                    tutor.current_id,
                )

def _generate_lesson_content():
    """
    Stream lesson content from the API and save to cache.

    Pulls tutor and adapter from session state directly since this is
    only called from _display_lesson_content which has no access to them.
    Determines presentation vs synthesis mode from the current element type.

    Returns:
        str: The generated markdown content, also saved to session state and disk.
    """
    tutor = st.session_state.tutor
    adapter = st.session_state.api_adapter

    if not adapter:
        st.info("No API connection — this lesson hasn't been generated yet.", icon=":material/wifi_off:")
        return None

    with st.spinner("Connecting to AI..."):
        mode = 'synthesis' if tutor.syllabus.get(tutor.current_id, {}).get('type') in ('module_synthesis', 'module_checkpoint') else 'presentation'
        raw_context = get_raw_context_data(
            tutor.syllabus, tutor.current_id,
            st.session_state.get('lesson_context_window', 3),
            mode=mode
        )
        final_prompt = build_final_prompt(
            mode,
            st.session_state.custom_prompts[mode],
            raw_context
        )

        model_id = resolve_model_id(
            st.session_state.active_provider,
            st.session_state.selected_models[mode]
        )
        
        # Stream response
        full_response = handle_stream_response(
            adapter=adapter,
            prompt=final_prompt,
            model=model_id,
            course_path=st.session_state.current_course_path,
            update_metrics_callback=update_course_metrics,
            element_id=tutor.current_id,
            generation_type=mode.capitalize(),
        )
        
        if not full_response:
            st.warning(
                "Content could not be generated. "
                "The API returned an empty or error response.\n\n"
                "**What to try:**\n"
                "- Hit the **Regenerate** button to try again\n"
                "- If it keeps failing, switch to a different model in Settings",
                icon=":material/warning:"
            )
            return None

        # Save to cache only on success
        st.session_state.card_content = full_response
        current_course_key = Path(st.session_state.current_course_path).name \
            if st.session_state.current_course_path else "unknown_course"

        if current_course_key not in st.session_state.content_cache:
            st.session_state.content_cache[current_course_key] = {}

        st.session_state.content_cache[current_course_key][st.session_state.tutor.current_id] = full_response
        save_cache_to_disk(current_course_key)

        return full_response

# =============================================================================
# Background
# =============================================================================

def _start_question_pool_generation(tutor, adapter, executor, course_filename):
    """
    Start background generation of question pool if needed.
    
    This runs while user reads the card.

    Args:
        tutor: SimpleTutor instance
        adapter: API adapter for generation
        executor: ThreadPoolExecutor for background submission
        course_filename: Course filename used as cache key
    """
    
    elem_type_check = tutor.get_current_element().get('type', '') if tutor else ''
    if elem_type_check in ('module_synthesis', 'module_checkpoint', 'final_test'):
        return
    
    # Skip if already generating or ready
    if st.session_state.questions or st.session_state.future_questions:
        return

    if not adapter:
        if not get_pool(course_filename, tutor.current_id):
            st.warning(
                "No API connection — questions for this lesson haven't been generated yet.",
                icon=":material/wifi_off:"
            )
            return
        _lesson_cap = st.session_state.get('lesson_max_questions', 0) or 999
        st.session_state.future_questions = executor.submit(
            get_questions_for_test,
            course_filename,
            tutor.current_id,
            _lesson_cap,
        )
        return

    # CRITICAL: Capture session state values BEFORE thread execution
    # Background threads cannot access st.session_state
    model_id = resolve_model_id(
        st.session_state.active_provider,
        st.session_state.selected_models['questions']
    )  
    prompt_key = 'questions'
    prompt_instruction = st.session_state.custom_prompts[prompt_key]
    context_window = st.session_state.get('lesson_context_window', 3)
    raw_context = get_raw_context_data(tutor.syllabus, tutor.current_id, context_window)
    _lc = tutor.syllabus.get(tutor.current_id, {}).get('lesson_content', [])
    pool_size = sum(b.get('questions', 0) for b in _lc) if isinstance(_lc, list) else None

    block_id = tutor.syllabus.get(tutor.current_id, {}).get('source_ids', ['UNKNOWN'])[0]

    def generate_pool():
        """Callback for pool generation - uses captured values, not session state."""
        return generate_questions_background(
            raw_context,
            adapter,
            model_id,
            prompt_instruction,
            course_filename,
            block_id,
            count=pool_size or None,
            element_id=tutor.current_id,
        )

    # Lessons show the full pool by default; capped if user set a limit
    _lesson_cap = st.session_state.get('lesson_max_questions', 0) or 999
    st.session_state.future_questions = executor.submit(
        get_questions_for_test,
        course_filename,
        tutor.current_id,
        _lesson_cap,
        generate_pool,
    )

# =============================================================================
# Action Bar & Test Start
# =============================================================================

def _render_action_bar(tutor, adapter, content_to_show, course_filename):
    """
    Render the VERIFY MASTERY / REPEAT MASTERY TEST button and keyboard hint.

    On click or force_test flag, dispatches to _handle_test_start which
    routes to the appropriate handler based on element type.

    Args:
        tutor: SimpleTutor instance
        adapter: API adapter, forwarded to test start handlers
        content_to_show: Lesson content (unused here, kept for signature consistency)
        course_filename: Course filename used as cache key
    """
    with st.container(key="action_bar"):
        is_passed = tutor.current_id in st.session_state.passed_elements
        test_btn_type = "secondary" if is_passed else "primary"
        elem_type = tutor.syllabus.get(tutor.current_id, {}).get('type', 'lesson')
        is_synthesis = elem_type in ('module_synthesis', 'module_checkpoint')

        if not is_passed:
            test_btn_label = "Verify Mastery"
            test_btn_icon = ":material/model_training:"
        else:
            test_btn_label = "Repeat Mastery Test"
            test_btn_icon = ":material/replay:"

        if is_synthesis:
            col_test, col_skip = st.columns([7, 3])
            with col_test:
                btn_clicked = st.button(
                    test_btn_label, icon=test_btn_icon,
                    type=test_btn_type, use_container_width=True
                )
                render_keyboard_hint('start_test')
            with col_skip:
                if st.button("Skip to Next", icon=":material/step_into:", help="Mark as passed & skip",
                             use_container_width=True):
                    handle_skip(tutor)
                render_keyboard_hint('skip')
        else:
            btn_clicked = st.button(
                test_btn_label, icon=test_btn_icon,
                type=test_btn_type, use_container_width=True
            )
            render_keyboard_hint('start_test')

        info_placeholder = st.empty()

        # Handle test start
        raw_context = get_raw_context_data(
            tutor.syllabus, tutor.current_id,
            st.session_state.get('lesson_context_window', 3)
        )
        if st.session_state.force_test or btn_clicked:
            _handle_test_start(adapter, raw_context, tutor, info_placeholder, course_filename)

def _handle_test_start(adapter, content_to_show, tutor, info_placeholder, course_filename):
    """
    Master dispatcher for test start — routes by element type.

    Dispatches to:
        module_synthesis    → _handle_module_synthesis_test_start
        module_checkpoint   → _handle_module_checkpoint_test_start
        final_test          → _handle_final_test_start
        lesson              → waits for future_questions or generates synchronously

    Args:
        adapter: API adapter for synchronous fallback generation
        content_to_show: Raw context passed to synchronous question generator
        tutor: SimpleTutor instance
        info_placeholder: st.empty() for spinner and error display
        course_filename: Course filename used as cache key
    """
    st.session_state.force_test = False
    elem_type = tutor.get_current_element().get('type', 'lesson') if tutor else 'lesson'

    # Retry path: show only the questions the user failed, skip pool entirely
    retry_qs = st.session_state.pop('retry_questions', None)
    if retry_qs and elem_type == 'lesson':
        st.session_state.questions = retry_qs
        st.session_state.answers = [None] * len(retry_qs)
        st.session_state.current_question_idx = 0
        tutor.state = 'TEST'
        save_full_state()
        st.rerun()
        return

    test_cnt = tutor.get_test_count(st.session_state.test_counts)

    if elem_type == 'module_synthesis':
        _handle_module_synthesis_test_start(tutor, info_placeholder, course_filename, test_cnt)
        return
    if elem_type == 'module_checkpoint':
        _handle_module_checkpoint_test_start(tutor, info_placeholder, course_filename, test_cnt)
        return
    if elem_type == 'final_test':
        _handle_final_test_start(tutor, info_placeholder, course_filename, test_cnt)
        return
    
    if not st.session_state.questions:
        with info_placeholder.container(border=False, height=60):
            if st.session_state.future_questions:
                with st.spinner("Preparing Test..."):
                    st.session_state.questions = st.session_state.future_questions.result()
            else:
                if not st.session_state.get('selected_models', {}).get('questions'):
                    with info_placeholder.container(border=False, height=60):
                        st.warning("Questions not available — configure an API key in Settings to generate them.", icon=":material/wifi_off:")
                    return
                model_id = resolve_model_id(
                    st.session_state.active_provider,
                    st.session_state.selected_models['questions']
                )
                prompt_instruction = st.session_state.custom_prompts['questions']
                _lc2 = tutor.syllabus.get(tutor.current_id, {}).get('lesson_content', [])
                _pool_size2 = sum(b.get('questions', 0) for b in _lc2) if isinstance(_lc2, list) else None
                _block_id2 = tutor.syllabus.get(tutor.current_id, {}).get('source_ids', ['UNKNOWN'])[0]
                with st.spinner("Generating Test..."):
                    def generate_pool():
                        """Callback using captured values."""
                        return generate_questions_background(
                            content_to_show,
                            adapter,
                            model_id,
                            prompt_instruction,
                            course_filename,
                            _block_id2,
                            count=_pool_size2 or None,
                            element_id=tutor.current_id
                        )

                    _lesson_cap = st.session_state.get('lesson_max_questions', 0) or 999
                    st.session_state.questions = get_questions_for_test(
                        course_filename,
                        tutor.current_id,
                        _lesson_cap,
                        generate_pool,
                    )

    st.session_state.future_questions = None
    
    if st.session_state.questions:
        st.session_state.answers = [None] * len(st.session_state.questions)
        st.session_state.current_question_idx = 0
        tutor.state = 'TEST'
        save_full_state()
        st.rerun()
    else:
        info_placeholder.error("Question generation failed. Hit **Verify Mastery** to try again. If the problem persists, try a different model or check your API key in Settings.", icon=":material/error:")

def _handle_module_synthesis_test_start(tutor, info_placeholder, course_filename, test_cnt):
    """Module synthesis draws from the already-generated subconcept pools."""
    
    current = tutor.get_current_element()
    children_ids = current.get('children_ids', [])
    
    if not children_ids:
        info_placeholder.error("No lessons found in this module.")
        return
    
    questions = get_questions_for_range(course_filename, children_ids, test_cnt)
    
    if not questions:
        info_placeholder.warning(
            "No question pools available yet for this module. "
            "Complete individual lessons first — questions are generated automatically as you study. "
            "Come back here once you've worked through some lessons."
        )
        return
    
    st.session_state.questions = questions
    st.session_state.answers = [None] * len(questions)
    st.session_state.current_question_idx = 0
    tutor.state = 'TEST'
    save_full_state()
    st.rerun()

def _handle_module_checkpoint_test_start(tutor, info_placeholder, course_filename, test_cnt):
    """Checkpoint draws from already-generated lesson pools, same as module_synthesis."""

    current = tutor.get_current_element()
    children_ids = current.get('children_ids', [])

    if not children_ids:
        info_placeholder.error("No lessons found for this checkpoint.")
        return

    questions = get_questions_for_range(course_filename, children_ids, test_cnt)

    if not questions:
        info_placeholder.warning(
            "No question pools available yet for this checkpoint. "
            "Complete the preceding lessons first — questions are generated automatically as you study."
        )
        return

    st.session_state.questions = questions
    st.session_state.answers = [None] * len(questions)
    st.session_state.current_question_idx = 0
    tutor.state = 'TEST'
    save_full_state()
    st.rerun()

def _handle_final_test_start(tutor, info_placeholder, course_filename, test_cnt):
    """Final test draws from ALL lesson pools across the entire course."""

    all_lesson_ids = [
        eid for eid, elem in tutor.syllabus.items()
        if isinstance(elem, dict) and elem.get('type') == 'lesson'
    ]

    if not all_lesson_ids:
        info_placeholder.error("No lessons found in course.")
        return

    questions = get_questions_for_range(course_filename, all_lesson_ids, test_cnt)

    if not questions:
        info_placeholder.warning(
            "No question pools available yet. "
            "Complete some lessons first — questions are generated automatically as you study."
        )
        return

    st.session_state.questions = questions
    st.session_state.answers = [None] * len(questions)
    st.session_state.current_question_idx = 0
    tutor.state = 'TEST'
    save_full_state()
    st.rerun()

# =============================================================================
# Final Test Card (special entry path)
# =============================================================================

def _auto_complete_course(course_filename: str) -> None:
    """
    Hide the course and add it to the 'Complete' SRS group.
    Idempotent — no-op if already in the 'Complete' group.
    """
    from src.managers import srs_manager as _srs

    srs_settings = _srs.load_settings()
    groups = srs_settings.setdefault("groups", {})
    complete = groups.setdefault("Complete", [])

    if course_filename not in complete:
        complete.append(course_filename)
        for gname, members in groups.items():
            if gname != "Complete" and course_filename in members:
                members.remove(course_filename)
        _srs.save_settings(srs_settings)
        if "srs_settings" in st.session_state:
            st.session_state.srs_settings = srs_settings

    sm = st.session_state.get("settings_manager")
    if sm:
        data = sm.load()
        hidden = set(data.get("hidden_courses", []))
        if course_filename not in hidden:
            hidden.add(course_filename)
            data["hidden_courses"] = sorted(hidden)
            sm.save(data)
            st.session_state.pop("hidden_courses_cache", None)


def _course_fully_passed(tutor) -> bool:
    """Return True if every lesson, checkpoint, and synthesis element is passed."""
    passed = st.session_state.get("passed_elements", set())
    ignored = st.session_state.get("ignored_elements", set())
    completable_types = ("lesson", "module_synthesis", "module_checkpoint")
    for eid, elem in tutor.syllabus.items():
        if isinstance(elem, dict) and elem.get("type") in completable_types:
            if eid not in passed and eid not in ignored:
                return False
    return True


def _render_final_test_card(tutor, adapter, course_filename):
    """Render the congratulations card for FINAL_TEST, with cache."""

    fully_passed = _course_fully_passed(tutor)
    if fully_passed:
        _auto_complete_course(course_filename)

    # Try cache first
    content = load_card_from_disk(course_filename, 'FINAL_TEST')

    if not content:
        model_id = resolve_model_id(
            st.session_state.active_provider,
            st.session_state.selected_models['presentation']
        )
        with st.spinner("Preparing your final message..."):
            content = generate_final_card(tutor.syllabus, adapter, model_id, course_filename)
        if content:
            save_card_to_disk(course_filename, 'FINAL_TEST', content)

    if fully_passed:
        st.info(
            ":material/check_circle: **Course complete!** "
            "This course has been moved to the **Complete** group in your SRS deck list "
            "and hidden from the course selector. "
            "You can restore it anytime via **Deck settings** in the sidebar.",
            icon=None,
        )
    else:
        st.warning(
            ":material/school: **You still have unfinished lessons.** "
            "If you skipped them intentionally, you can mark the whole course as completed now — "
            "it will be hidden from the active course list and moved to the **Complete** group.",
        )
        col_btn, _ = st.columns([3, 7])
        with col_btn:
            if st.button(
                "Mark as Complete",
                icon=":material/done_all:",
                use_container_width=True,
                key="final_mark_complete",
            ):
                _auto_complete_course(course_filename)
                st.rerun()

    with st.container(key="lesson_window"):
        if content:
            st.markdown(content)
        else:
            st.error("Could not generate congratulations message.")

    test_cnt = tutor.get_test_count(st.session_state.test_counts)

    btn_clicked = st.button(
        f"Begin Final Test ({test_cnt} questions)",
        icon=":material/military_tech:",
        type="primary",
        use_container_width=True
    )

    info_placeholder = st.empty()

    if st.session_state.get('force_test') or btn_clicked:
        _handle_final_test_start(tutor, info_placeholder, course_filename, test_cnt)
    else:
        with info_placeholder:
            render_keyboard_hint('start_test')