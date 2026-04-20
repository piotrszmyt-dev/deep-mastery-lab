"""
Course Generator Renderer
=========================
Streamlit UI layer for the course generation pipeline. Manages all screens,
state transitions, and user interactions from raw text input to finished course.

This file is the render counterpart to course_generator.py — it owns the UI
and delegates all heavy computation to ProductionCourseGenerator.

Pipeline Flow:
    None       → entry point, generator card not yet opened
    INPUT      → user enters title, language, source text, model, advanced settings
    CHUNK_REVIEW → QC screen: inspect extracted paragraphs, set chunk boundaries
    RUNNING    → live progress screen: async pipeline runs, logs stream in real time
    MODULE_REVIEW → user adjusts lesson-to-module grouping before finalization
    DONE       → completion screen with stats, download, and open-in-tutor actions

Screen Functions (in pipeline order):
    show_generator_v5()         Main router — wraps all screens in a shared card
    show_input_form()           Screen 1: text input + validation + time estimate
    show_chunk_review()         Screen 2: QC paragraph editor + boundary controls
    show_generation_progress()  Screen 3: async pipeline runner + live log console
    show_module_review()        Screen 4: module boundary editor + finalization
    show_completion()           Screen 5: stats, download JSON, open in Mastery Lab

QC Helpers (support CHUNK_REVIEW and RUNNING):
    build_qc_items()            Parse raw text into editable item list
    build_pages_from_qc()       Convert approved items + boundaries → pages_dict + master_index
    _detect_header()            Heuristic to classify a line as header or paragraph

Session State:
    generator_v5_state  str   Current screen identifier (see flow above)
    generator_v5_data   dict  All pipeline data — inputs, intermediate results, metrics, logs
                              Key fields: title, source_text, model_id, qc_data,
                              pages_dict, master_index, lesson_list, module_suggestion,
                              module_boundaries, result, logs, stats
"""

import streamlit as st
import asyncio
from pathlib import Path
import re
import time
import json
import os
import math
import streamlit.components.v1 as components

from src.managers.models_manager import get_models
from src.core.course_generator import ProductionCourseGenerator, paragraph_weight

# ========================================
# SESSION STATE SETUP
# ========================================

def init_generator_state():
    """Initialize session state for generator."""
    
    if 'generator_v5_state' not in st.session_state:
        st.session_state.generator_v5_state = None 
    
    if 'generator_v5_data' not in st.session_state:
        st.session_state.generator_v5_data = _fresh_generator_data()

# ========================================
# MAIN ROUTER
# ========================================

def show_generator_v5():
    """Main router. Renders the correct screen based on generator_v5_state:
    INPUT → CHUNK_REVIEW → RUNNING → MODULE_REVIEW → DONE."""
    state = st.session_state.generator_v5_state
    
    with st.container(key="generator_card"):
        
        c_head, c_back = st.columns([5, 1], vertical_alignment="center")
        
        with c_head:
            st.markdown(
                '<div class="card-title"><span class="material-icons">rocket_launch</span> Course Generator</div>',
                unsafe_allow_html=True
            )
        
        with c_back:
            if st.button("Back", icon=":material/arrow_back:", use_container_width=True):
                st.session_state.generator_v5_state = None
                st.session_state['_scroll_top'] = True
                st.rerun()
        
        view_container = st.empty()

        with view_container.container():
            if state == 'INPUT':
                show_input_form()
            elif state == 'RUNNING':
                show_generation_progress()
            elif state == 'DONE':
                show_completion(view_container)
            elif state == 'MODULE_REVIEW':
                show_module_review()
            elif state == 'CHUNK_REVIEW':
                show_chunk_review(view_container)

# ========================================
# SCREEN 1: INPUT FORM
# ========================================

def show_input_form():
    """Input screen: title, language, source text, advanced settings, and model selection.
    Validates input, computes time estimate, then routes to CHUNK_REVIEW."""
    should_scroll = st.session_state.pop('_scroll_top', False)
    _scroll_to_top(should_scroll, delay=200, position=150)
    title = st.text_input(
        "Course Title:", 
        value=st.session_state.generator_v5_data['title'],
        placeholder="For example: Fuse Reactor Fundamentals"
    )

    output_language = st.text_input(
        "Output Language",
        value=st.session_state.generator_v5_data.get('output_language', 'English'),
        placeholder="e.g. English, Polish, Spanish...",
        help="Language for all generated course content"
    )
    
    source_text = st.text_area(
        "Paste Raw Text:", 
        value=st.session_state.generator_v5_data['source_text'],
        height=300,
        placeholder=(
            "Paste raw text here.\n\n"
            "BEFORE PASTING — quick checklist:\n"
            "  ✦ One chapter at a time for managable quality check. You can group the courses later into books.  \n"
            "  ✦ Add ## before each section header (the algorithm detects most, but may miss some)\n"
            "  ✦ Convert tables and bullet lists to prose sentences\n"
            "  ✦ Remove non-learning material: references, figure captions, footnotes, links\n"
            "  ✦ Prefer primary sources: textbooks, official docs, lecture notes, Wikipedia\n"
            "  ✦ Avoid AI-generated summaries (NotebookLM, ChatGPT notes) — errors get tested as facts\n\n"
            "Working from a PDF? Read prompt_for_pdf_extraction.md in the project folder first. You will find complete solution there. "
        ),
        help="Accepts any raw text — Wikipedia articles, textbook chapters, lecture notes"
    )
    
    # Word count & estimate
    if source_text:
        words = len(source_text.split())
        chunk_size_est   = st.session_state.get('_input_chunk_size', st.session_state.generator_v5_data.get('chunk_size', 1))
        max_parallel_est = st.session_state.get('_input_max_parallel', st.session_state.generator_v5_data.get('max_parallel', 5))

        # Chunk count
        words_per_chunk = chunk_size_est * 600
        raw_chunks = max(1, round(words / words_per_chunk))

        # Stage 1: time per wave scales with chunk size
        # chunk_size 1→1.0min, 2→1.5min, 3→2.0min, 4→2.5min per wave
        mins_per_wave = 1.0 + (chunk_size_est - 1) * 0.5
        waves_1a = math.ceil(raw_chunks / max_parallel_est)
        stage1_min = waves_1a * mins_per_wave
        stage1_max = stage1_min * 1.5

        # Stage 2: one wave's worth of stage 1 time, scaled ×1.0 to ×2.0
        stage2_min = stage1_min / waves_1a * 1.0   # same as one wave
        stage2_max = stage1_min / waves_1a * 2.0

        total_min = round(stage1_min + stage2_min + 0.5)
        total_max = round(stage1_max + stage2_max + 0.5)

        pages = words // 600
        st.markdown(f"""
        <div class="generator-stat-box">
            <div class="stat-item">
                <span class="stat-label">Words</span>
                <div class="stat-value">{words:,}</div>
            </div>
            <div class="stat-item">
                <span class="stat-label">Pages</span>
                <div class="stat-value">{pages}</div>
            </div>
            <div class="stat-item">
                <span class="stat-label">Chunks</span>
                <div class="stat-value">{raw_chunks}</div>
            </div>
            <div class="stat-item">
                <span class="stat-label">Waves</span>
                <div class="stat-value">{waves_1a}</div>
            </div>
            <div class="stat-item">
                <span class="stat-label">Est. Time</span>
                <div class="stat-value-accent">{total_min}–{total_max} min</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("###")
    
    with st.expander("Advanced Settings"):
        c_set1, c_set2 = st.columns(2)
        with c_set1:
            max_parallel = st.number_input("Max parallel requests", min_value=1, max_value=10, value=st.session_state.generator_v5_data.get('max_parallel', 5), step=1, key="_input_max_parallel")
        with c_set2:
            chunk_size = st.number_input("Pages per chunk", min_value=1, max_value=5, value=st.session_state.generator_v5_data.get('chunk_size', 1), step=1, key="_input_chunk_size")

    active_provider = st.session_state.get("active_provider", "openrouter")
    provider_models = get_models(active_provider)
    available_model_ids = [m["model_id"] for m in provider_models]
    available_model_names = [m["display_name"] for m in provider_models]

    selected_name = st.selectbox("Model AI:", available_model_names)
    model_id = available_model_ids[available_model_names.index(selected_name)]
    st.write("")
    

    
    # VALIDATION
    min_chars = 300
    current_chars = len(source_text.strip())
    
    if source_text and current_chars < min_chars:
        # Class: generator-warning
        st.markdown(
            f"<div class='generator-warning'>"
            f"<span class='material-icons' style='font-size: 16px;'>warning</span> "
            f"Text is too short. Required: {min_chars}, Current: {current_chars}.</div>", 
            unsafe_allow_html=True
        )
    
    can_start = bool(title.strip() and current_chars >= min_chars)
    
    if st.button("Move to Quality Check", icon=":material/rocket_launch:", type="primary", disabled=not can_start, use_container_width=True):
        st.session_state.generator_v5_data.update({
            'title': title,
            'source_text': source_text,
            'model_id': model_id,
            'max_parallel': max_parallel,
            'chunk_size': chunk_size,
            'output_language': output_language, 
            'current_step': 0,
            'progress': 0,
            'stats': {} 
            
        })

        qc = build_qc_items(source_text)

        # Default boundaries at word-count intervals, snapped to nearest header
        words_per_chunk = chunk_size * 600
        items = qc['items']
        boundaries = [0]
        cumulative = 0
        for i, item in enumerate(items):
            cumulative += len(item['text'].split())
            if cumulative >= words_per_chunk:
                # Snap forward to the next header within 5 items, if one exists
                snap_target = i
                for lookahead in range(i, min(i + 6, len(items))):
                    if items[lookahead]['type'] == 'h1':
                        snap_target = lookahead
                        break
                if snap_target not in boundaries:
                    boundaries.append(snap_target)
                cumulative = 0
        qc['boundaries'] = sorted(boundaries)

        st.session_state.generator_v5_data['qc_data'] = qc
        st.session_state.generator_v5_state = 'CHUNK_REVIEW'
        st.session_state['_scroll_top'] = True
        st.rerun()

# ========================================
# SCREEN 2: CHUNK REVIEW (QC)
# ========================================

def show_chunk_review(view_container):
    """QC screen: lets user inspect extracted paragraphs, toggle headers/paragraphs,
    set chunk boundaries, merge or delete items. On confirm → builds pages_dict
    and master_index via build_pages_from_qc(), then routes to RUNNING."""
    should_scroll = st.session_state.pop('_scroll_top', False)
    _scroll_to_top(should_scroll)

    data   = st.session_state.generator_v5_data
    qc     = data['qc_data']
    items  = qc['items']
    course_title = data.get('title', 'Course')

    # Work with a live set — recomputed each render
    boundaries = set(qc['boundaries'])
    chunk_size_pages = data.get('chunk_size', 3)
    words_per_llm_call = chunk_size_pages * 600

    st.markdown(
        "### <span class='material-icons' style='vertical-align: bottom; color: var(--primary-color);'>fact_check</span> Source Quality Check", 
        unsafe_allow_html=True
    )
    
    st.caption(
        "**Scroll through the extracted text below** to give it a quick manual polish. Scanning through learning material is also the very first step to mastery."
    )
    
    st.caption(
        """
        **Your curation checklist:**
        * **Verify Headers:** Check that section titles are correctly marked as Headers (**H1** icon) and body text as Paragraphs (**¶** icon). Click the icon to toggle them!
        * **Set Boundaries:** Ensure every chunk starts with a clear Header. Use the scissors to snip a new boundary, or click an active divider to remove it.
        * **Consolidate Ideas:** Use the merge button (⬇) to combine fragmented bullet lists or scattered sentences into single, readable blocks.
        * **Clear the Noise:** Click the trash can to remove non-educational artifacts like page numbers, figure captions, or publisher notes.
        """
    )

    col_back, col_go = st.columns([4, 6])
    with col_back:
        if st.button("Back to Content Input", icon=":material/arrow_back:", key="btn_back_chunk_review", use_container_width=True):
            st.session_state.generator_v5_state = 'INPUT'
            st.session_state['_scroll_top'] = True
            st.rerun()
    with col_go:
        if st.button("Start Generation", icon=":material/rocket_launch:", type="primary", use_container_width=True):
            view_container.empty()
            time.sleep(0.2)
            st.session_state.generator_v5_state = 'RUNNING'
            st.session_state['_scroll_top'] = True
            st.session_state.generator_v5_data['current_step'] = 0
            st.rerun()

    # ── Stats ─────────────────────────────────────────────────────
    visible_items = [it for it in items if not it['deleted']]
    visible_count = len(visible_items)
    total_questions = sum(
        it.get('q_override', paragraph_weight(it['text']))
        for it in visible_items if it['type'] == 'p'
    )
    st.caption(f"**{len(boundaries)} chunks** · **{visible_count} paragraphs** · **{total_questions} questions** — Inspect scrollable area below :material/arrow_cool_down:")
    st.markdown("---")
    # ── Item list ─────────────────────────────────────────────────────────────
    active = [(i, item) for i, item in enumerate(items) if not item['deleted']]
    sorted_b = sorted(boundaries)

    chunk_size_pages = data.get('chunk_size', 3)
    words_per_page = words_per_llm_call
    cumulative_words = 0
    page_suggestion_indices = set()
    for i, item in active:
        cumulative_words += len(item['text'].split())
        if cumulative_words >= words_per_page:
            page_suggestion_indices.add(i)
            cumulative_words = 0
    with st.container(height=600, border=False, key="chunk_review"):
        for list_pos, (orig_idx, item) in enumerate(active):
            is_boundary = orig_idx in boundaries
            is_first    = orig_idx == sorted_b[0] if sorted_b else True
            if orig_idx in page_suggestion_indices and orig_idx not in boundaries and list_pos > 0:
                st.markdown(
                    '<div style="border-top:1px dashed #888;margin:6px 0 2px 0;'
                    'font-size:10px;opacity:0.4;text-align:center">'
                    '· · · suggested page break · · ·</div>',
                    unsafe_allow_html=True
                )
            # Chunk divider above the first item of each chunk
            if is_boundary:
                chunk_num = sorted_b.index(orig_idx) + 1
                label = item['text'][:55] if item['type'] == 'h1' else f"↳ inherits: {course_title}"
                st.caption(f":material/segment: Chunk {chunk_num} ---------------------------- ✂ ")

            # Columns: [H/P] [merge↓] [delete] [cut] [text]
            c_tools, c_tx = st.columns([3, 7], vertical_alignment="center")

            pid = item['id']

            with c_tools:
                b1, b2, b3, b4 = st.columns(4) 

                with b1:
                    btn_icon = ":material/format_h1:" if item['type'] == 'p' else ":material/format_paragraph:"
                    tip = "Promote to header" if item['type'] == 'p' else "Demote to paragraph"
                    
                    if st.button("", icon=btn_icon, key=f"hp_{pid}", help=tip, use_container_width=True):
                        item['type'] = 'h1' if item['type'] == 'p' else 'p'
                        st.rerun()
                with b2:
                    next_items = [(j, it) for j, it in enumerate(items)
                                if j > orig_idx and not it['deleted']]
                    if st.button(
                            "", 
                            icon=":material/arrow_downward:", 
                            key=f"mg_{pid}", 
                            help="Merge with item below",
                            disabled=not next_items, 
                            use_container_width=True
                        ):
                        if next_items:
                            nj, nit = next_items[0]
                            items[orig_idx]['text'] = item['text'] + ' ' + nit['text']
                            items[orig_idx]['type'] = 'p'
                            items[nj]['deleted'] = True
                            boundaries.discard(nj)
                            qc['boundaries'] = sorted(boundaries)
                            st.rerun()
                with b3:
                    if st.button("", icon=":material/delete:", key=f"dl_{pid}", help="Remove paragraph", use_container_width=True):
                        items[orig_idx]['deleted'] = True
                        if orig_idx in boundaries and orig_idx != sorted_b[0]:
                            boundaries.discard(orig_idx)
                            next_alive = [j for j, it in enumerate(items)
                                        if j > orig_idx and not it['deleted']]
                            if next_alive:
                                boundaries.add(next_alive[0])
                        qc['boundaries'] = sorted(boundaries)
                        st.rerun()
                with b4:
                    if is_first:
                        # Replaced HTML with a disabled button using the Home icon
                        st.button("", icon=":material/home:", key=f"ct_{pid}_home", 
                                help="Top of document", disabled=True, use_container_width=True)
                                
                    elif is_boundary:
                        # Using a horizontal rule to represent the active divider
                        if st.button("", icon=":material/line_start_circle:", key=f"ct_{pid}", help="Remove chunk boundary",
                                    type="primary", use_container_width=True):
                            boundaries.discard(orig_idx)
                            qc['boundaries'] = sorted(boundaries)
                            st.rerun()
                            
                    else:
                        # Using the standard Material scissors icon
                        if st.button("", icon=":material/content_cut:", key=f"ct_{pid}", help="Start new chunk here",
                                    use_container_width=True):
                            boundaries.add(orig_idx)
                            qc['boundaries'] = sorted(boundaries)
                            st.rerun()

            # Text content
            with c_tx:
                if item['type'] == 'h1':
                    st.markdown(f"**{item['text']}**")
                else:
                    formula_val = paragraph_weight(item['text'])
                    current_val = item.get('q_override', formula_val)
                    new_val = st.number_input(
                        "Questions",
                        min_value=1, max_value=50,
                        value=current_val,
                        key=f"qn_{pid}",
                        help=f"Formula estimate: {formula_val}. Override to cap or boost the question count for this paragraph.",
                    )
                    if new_val != formula_val:
                        item['q_override'] = new_val
                    elif 'q_override' in item:
                        del item['q_override']
                    st.caption(item['text'])

    # ── Footer ────────────────────────────────────────────────────────────────

    # Warn about headerless chunks
    headerless = 0
    for idx, start in enumerate(sorted_b):
        end = sorted_b[idx + 1] if idx + 1 < len(sorted_b) else len(items)
        first_active = next(
            (items[i] for i in range(start, end) if not items[i]['deleted']), None
        )
        if first_active and first_active['type'] != 'h1':
            headerless += 1
    if headerless:
        st.caption(f":material/info: {headerless} chunk(s) start without a header — they'll inherit the course title automatically.")

def _detect_header(text: str) -> bool:
    """
    Loose detection — catches ~80% of cases, user fixes the rest in QC.
    Rule: markdown # prefix  OR  fewer than 11 words.
    Short lines are almost never body text; they're titles, headings, labels.
    """
    if re.match(r'^#{1,3}\s+\S', text):
        return True
    word_count = len(text.split())
    if word_count <= 11:
        return True
    return False


def build_qc_items(text: str) -> dict:
    """
    Split raw text into one item per line. Every non-empty line gets a PXXX.
    No paragraph merging — user handles that in the QC UI.
    Returns {'items': [...], 'boundaries': [...]} for the QC UI.
    """
    # Normalize wiki-style headers only — no other structural changes
    text = re.sub(r'={2,}\s*(.+?)\s*={2,}', r'## \1', text)
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'\[citation needed\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[nb \d+\]', '', text)

    items = []
    pid_counter = 1
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue         
        if len(line) < 2:
            continue          
        pid = f"P{pid_counter:03d}"
        pid_counter += 1
        items.append({
            'id':      pid,
            'text':    line,
            'type':    'h1' if _detect_header(line) else 'p',
            'deleted': False,
        })

    return {'items': items, 'boundaries': [0]}

def build_pages_from_qc(items: list, boundaries: list, course_title: str) -> dict:
    """
    After QC confirmation: rebuild pages_dict + master_index from
    approved items + boundaries. Each boundary = one LLM chunk.
    - IDs are reassigned sequentially (gaps from deletions/merges eliminated)
    - h1 items become plain markdown headers (no PXXX tag — LLM reads them as context)
    - p items get clean sequential PXXX tags and go into master_index
    - Headerless chunks inherit the course title as a synthetic header
    """
    active_items = [item for item in items if not item['deleted']]
    boundary_set = set(boundaries)

    # Build orig_index → active position map for boundary lookup
    orig_to_active = {}
    for active_pos, item in enumerate(active_items):
        orig_idx = items.index(item)  # original position in full list
        orig_to_active[orig_idx] = active_pos

    # Boundary set uses original indices — convert to active positions
    active_boundary_positions = set()
    for orig_idx in boundary_set:
        # Find first active item at or after this boundary
        for orig_i, item in enumerate(items):
            if orig_i >= orig_idx and not item['deleted']:
                active_boundary_positions.add(id(item))
                break

    master_index = {}
    q_overrides  = {}
    pages_dict = {}
    chunk_num = 1
    current_lines = []
    pid_counter = 1  # sequential, gap-free

    for active_pos, item in enumerate(active_items):
        is_boundary = id(item) in active_boundary_positions

        # Flush previous chunk on boundary (skip the very first)
        if is_boundary and current_lines:
            pages_dict[f"page_{chunk_num}"] = '\n\n'.join(current_lines)
            chunk_num += 1
            current_lines = []

        # Headerless chunk opening → inject course title
        if not current_lines and item['type'] != 'h1':
            current_lines.append(f"## {course_title}")

        if item['type'] == 'h1':
            # Headers: plain markdown, no PXXX — LLM reads as structural context only
            current_lines.append(f"## {item['text'].lstrip('#').strip()}")
        else:
            # Paragraphs: assign clean sequential ID
            new_pid = f"P{pid_counter:03d}"
            pid_counter += 1
            master_index[new_pid] = item['text']
            current_lines.append(f"[{new_pid}] {item['text']}")
            # Carry user-set question count override to the new PID
            if 'q_override' in item:
                q_overrides[new_pid] = item['q_override']

    if current_lines:
        pages_dict[f"page_{chunk_num}"] = '\n\n'.join(current_lines)

    # Debug output
    debug_dir = Path("data/debug/preprocessor")
    debug_dir.mkdir(parents=True, exist_ok=True)
    with open(debug_dir / "pages_for_llm.txt", 'w', encoding='utf-8') as f:
        for key, content in pages_dict.items():
            f.write(f"{'='*60}\n=== {key.upper()} ===\n{'='*60}\n{content}\n\n")
    with open(debug_dir / "master_index.json", 'w', encoding='utf-8') as f:
        import json as _json
        _json.dump(master_index, f, indent=2, ensure_ascii=False)

    print(f"[OK] QC -> {len(active_items)} items -> {len(pages_dict)} chunks, {len(master_index)} indexed paragraphs, {len(q_overrides)} q_overrides")
    return {"pages": pages_dict, "master_index": master_index, "q_overrides": q_overrides}

# ========================================
# SCREEN 3: GENERATION PROGRESS
# ========================================

def show_generation_progress():
    """Live progress screen: runs the async generation pipeline, streams log updates,
    and handles abort/failure. On success routes to MODULE_REVIEW or DONE."""
    should_scroll = st.session_state.pop('_scroll_top', False)
    _scroll_to_top(should_scroll, delay=1000)

    data = st.session_state.generator_v5_data

    if data.get('_pipeline_failed'):
            err = data.get('_pipeline_error', '')
            st.error(f"**Course generation failed.** {err}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Try Again", icon=":material/refresh:", use_container_width=True):
                    data['current_step'] = 0
                    data['_pipeline_failed'] = False
                    data['_abort_requested'] = False
                    data['_metric_lessons'] = 0 
                    data['_metric_modules'] = 0
                    st.rerun()
            with c2:
                if st.button("Change Settings", icon=":material/settings:", use_container_width=True):
                    st.session_state.generator_v5_state = 'INPUT'
                    st.rerun()
            return
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Abort Generation", icon=":material/stop_circle:", type="secondary", use_container_width=True, key="abort_gen_btn"):
        st.session_state.generator_v5_data['_abort_requested'] = True
        if data.get('generator'):
            data['generator']._abort_requested = True
    st.markdown(
        "#### <span class='material-icons spinner-icon'>settings</span> Processing...",
        unsafe_allow_html=True
    )

    progress_label = st.empty()
    progress_bar   = st.empty()
    status_box     = st.empty()

    # Live metrics row
    col1, col2, col3 = st.columns(3)
    metric_lessons = col1.empty()
    metric_modules = col2.empty()
    metric_time    = col3.empty()
    metric_lessons.metric("Lessons:", "—")
    metric_modules.metric("Modules:", "—")
    metric_time.metric("Time Passed", "0s")

    data.setdefault('_metric_lessons', 0)
    data.setdefault('_metric_modules', 0)
    data.setdefault('_lessons_total', 1)
    data.setdefault('_lessons_done', 0)
    data.setdefault('_progress_stage', 1)
    
    _start_time = time.time()

    if data['current_step'] == 0:
        if 'pages_dict' not in data:
            with st.spinner("Preparing chunks for generation..."):
                qc = data['qc_data']
                course_title = data.get('title', 'Course')
                
                result = build_pages_from_qc(qc['items'], sorted(qc['boundaries']), course_title)
                
                data['pages_dict']   = result['pages']
                data['master_index'] = result['master_index']
                data['q_overrides']  = result['q_overrides']
        try:
            from ...api.course_generator_adapter import CourseGeneratorAdapter
        except ImportError:
            from src.api.course_generator_adapter import CourseGeneratorAdapter

        active_provider = st.session_state.get("active_provider", "openrouter")
        api_key = st.session_state.get("api_keys", {}).get(active_provider)
        if not api_key and 'api_adapter' in st.session_state and st.session_state.api_adapter:
            try: api_key = st.session_state.api_adapter.client.api_key
            except AttributeError: pass
        if not api_key:
            api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            st.error("❌ Missing API Key!")
            st.stop()

        adapter = CourseGeneratorAdapter(
            api_key=api_key,
            provider=active_provider,
        )
        generator = ProductionCourseGenerator(
            adapter=adapter,
            model_id=data['model_id'],
            chunk_size=data.get('chunk_size', 3),
            language=data.get('output_language', 'English'),
            max_parallel=data.get('max_parallel', 5),
            title=data.get('title', '')
        )
        st.session_state.generator_v5_data['generator'] = generator
        st.session_state.generator_v5_data['current_step'] = 1
        st.session_state.generator_v5_data['generation_start_time'] = time.time()
        st.session_state.generator_v5_data['logs'] = []
        st.session_state.generator_v5_data['_lessons_total'] = 0
        st.session_state.generator_v5_data['_lessons_done']  = 0
        st.session_state.generator_v5_data['_progress_stage'] = 1

    if data.get('generator'):
        generator = data['generator']
        generator.master_index = data.get('master_index', {})
        generator.q_overrides  = data.get('q_overrides', {})
        pages_dict = data['pages_dict']

        if 'logs' not in data:
            data['logs'] = []

        def on_progress(step, message, step_data=None):
            step_data = step_data or {}
            elapsed = int(time.time() - _start_time)
            time_str = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else f"{elapsed}s"

            # ── Progress counters ───────────────────────────────────
            if step == 3:
                data['_progress_stage'] = 2 

            if step == '3_lesson':
                data['_lessons_done'] = data.get('_lessons_done', 0) + 1

            stage         = data.get('_progress_stage', 1)
            lessons_total = max(data.get('_lessons_total', 1), 1)
            lessons_done  = data.get('_lessons_done', 0)

            if stage == 1:
                bar_done, bar_total = 0, 1
                label_txt = "Parsing &amp; mapping structure..."
            else:
                bar_done  = lessons_done
                bar_total = lessons_total
                label_txt = f"Finalizing Structure &nbsp;·&nbsp; Lessons {lessons_done}/{lessons_total}"

            pct = min(100, int(bar_done / bar_total * 100))
            hue = int(pct / 100 * 120)

            progress_label.markdown(
                f'<div style="font-size:0.85em;opacity:0.65;margin-bottom:4px">{label_txt}</div>',
                unsafe_allow_html=True
            )
            progress_bar.markdown(
                f'<div class="progress-container">'
                f'<div class="progress-fill" style="--bar-hue:{hue};width:{pct}%"></div>'
                f'</div>',
                unsafe_allow_html=True
            )

            # ── Icon + color logic ──────────────────────────────────
            step_titles = {
                1:          "Parsing",
                2:          "Structure",
                3:          "Final Structure",      
                '3_lesson': "Success", 
                'warning':  "Warning",
                'error':    "Error",
            }
            step_icons = {
                1:          "travel_explore",
                2:          "architecture",
                3:          "hourglass_top",  
                '3_lesson': "task_alt",       
                'warning':  "warning",
                'error':    "error_outline",
            }
            icon = step_icons.get(step, "hourglass_top")
            icon_color = "#8FBCBB"
            msg_lower = message.lower()
            if step == 'error':
                icon, icon_color = "error_outline", "#BF616A"
            elif step == 'warning':
                icon, icon_color = "warning", "#EBCB8B"
            elif "identified" in msg_lower or "lessons" in msg_lower or "modules" in msg_lower:
                icon, icon_color = step_icons.get(step, "check_circle"), "#A3BE8C"

            # ── Metrics update ──────────────────────────────────────
            if step == 1:
                data['_metric_lessons'] = step_data.get('total_lessons', 0)
                metric_lessons.metric("Lessons", str(data['_metric_lessons']))

            if step == 2:
                data['_metric_modules'] = step_data.get('module_count', 0)
                data['_metric_lessons'] = step_data.get('lesson_count', data.get('_metric_lessons', 0))
                data['_lessons_total']  = data['_metric_lessons'] 
                metric_lessons.metric("Lessons", str(data['_metric_lessons']))
                metric_modules.metric("Modules", str(data['_metric_modules']))

            metric_time.metric("Time Passed", time_str)

            # ── Log append ─────────────────────────────────────────
            logs = data['logs']
            if not logs or logs[-1]['message'] != message:
                logs.append({
                    'icon': icon, 'icon_color': icon_color,
                    'title': step_titles.get(step, "Processing"),
                    'message': message, 'time': time.strftime("%H:%M:%S")
                })
                if len(logs) > 20:
                    data['logs'] = logs[-20:]

            log_html_items = []
            for log in reversed(logs):
                log_html_items.append(
                    f'<div class="generator-console-step">'
                    f'<span class="material-icons console-icon" style="color:{log["icon_color"]};">{log["icon"]}</span>'
                    f'<div>'
                    f'<strong class="console-title" style="font-size:0.9em;">{log["title"]}</strong>'
                    f'<span style="color:#4C566A;font-size:0.8em;margin-left:10px;">{log["time"]}</span>'
                    f'<div class="console-message" style="margin-top:2px;">{log["message"]}</div>'
                    f'</div></div>'
                )
            status_box.markdown(
                f'<div class="generator-console" style="height:300px;display:block;">{"".join(log_html_items)}</div>',
                unsafe_allow_html=True
            )

        try:
            result = asyncio.run(
                generator.generate_course_async(
                    title=data['title'],
                    pages_dict=pages_dict,
                    master_index=data['master_index'],
                    on_progress=on_progress
                )
            )
            data['result'] = result
            if not result.get('success', True):
                # Pipeline aborted — show error in console, stay on RUNNING screen
                error_msg = result.get('error', 'Unknown error')
                on_progress('error', f"Pipeline failed: {error_msg}")
                st.session_state.generator_v5_data['_pipeline_failed'] = True
                st.session_state.generator_v5_data['_pipeline_error'] = error_msg
                st.rerun()
            elif result.get('status') == 'awaiting_module_review':
                data['lesson_list'] = result['lesson_list']
                data['module_suggestion'] = result['module_suggestion']
                boundaries = []
                for mod in result['module_suggestion'].get('modules', []):
                    lessons_in_mod = mod.get('contains_lessons', [])
                    if lessons_in_mod:
                        boundaries.append(lessons_in_mod[0])
                first_id = result['lesson_list'][0].get('lesson_id') or result['lesson_list'][0].get('topic_id', '')
                data['module_boundaries'] = [b for b in boundaries if b != first_id]
                st.session_state.generator_v5_state = 'MODULE_REVIEW'
            else:
                st.session_state.generator_v5_state = 'DONE'
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")
            st.exception(e)

# ========================================
# SCREEN 4: MODULE REVIEW
# ========================================

def show_module_review():
    """Module structure review: lets user adjust lesson-to-module boundaries via
    checkboxes. On confirm calls resume_after_review() and routes to DONE."""
    if st.session_state.pop('_scroll_top', False):
        _scroll_to_top()
    data       = st.session_state.generator_v5_data
    lessons    = data.get('lesson_list', [])
    suggestion = data.get('module_suggestion', {})
    master_index = data.get('master_index', {})

    st.markdown(
        "### <span class='material-icons header-icon'>tune</span> Fine-Tune Course Structure",
        unsafe_allow_html=True
    )
    st.caption(
        "We've drafted a baseline grouping for your course, but you have the final say. "
        "Check a box to start a new module, or uncheck it to group the lesson with the one above."
    )

    # Build module title and subtitle lookups
    module_titles    = {}
    module_subtitles = {}
    for mod in suggestion.get('modules', []):
        first = mod.get('contains_lessons', [None])[0]
        if first:
            module_titles[first]    = mod.get('title', '')
            module_subtitles[first] = mod.get('subtitle', '')

    # Initialize checkbox state on first render
    initial_boundaries = set(data.get('module_boundaries', []))
    for lesson in lessons:
        lid = lesson.get('lesson_id') or lesson.get('topic_id', '?')
        if f"boundary_{lid}" not in st.session_state:
            st.session_state[f"boundary_{lid}"] = lid in initial_boundaries

    def is_boundary(lid):
        return st.session_state.get(f"boundary_{lid}", False)

    # ── Stats + Confirm button ─────────────────────────────────────────────
    active_boundaries = sum(
        1 for lesson in lessons[1:]
        if is_boundary(lesson.get('lesson_id') or lesson.get('topic_id', ''))
    )
    module_count = active_boundaries + 1
    st.markdown("\n")
    if st.button(
        "Confirm and Finalize Generation",
        icon=":material/check_circle:",
        type="primary",
        use_container_width=True
    ):
        module_assignments = []
        current_mod_lessons = []
        mod_num = 1

        for i, lesson in enumerate(lessons):
            lid = lesson.get('lesson_id') or lesson.get('topic_id', '?')
            if i > 0 and is_boundary(lid) and current_mod_lessons:
                suggested_title    = module_titles.get(current_mod_lessons[0], f"Module {mod_num}")
                suggested_subtitle = module_subtitles.get(current_mod_lessons[0], '')
                module_assignments.append({
                    'module_id':  f"M{mod_num:02d}",
                    'title':      suggested_title,
                    'subtitle':   suggested_subtitle,
                    'lesson_ids': current_mod_lessons
                })
                mod_num += 1
                current_mod_lessons = []
            current_mod_lessons.append(lid)

        if current_mod_lessons:
            suggested_title    = module_titles.get(current_mod_lessons[0], f"Module {mod_num}")
            suggested_subtitle = module_subtitles.get(current_mod_lessons[0], '')
            module_assignments.append({
                'module_id':  f"M{mod_num:02d}",
                'title':      suggested_title,
                'subtitle':   suggested_subtitle,
                'lesson_ids': current_mod_lessons
            })

        original_mapping = {}
        for mod in suggestion.get('modules', []):
            for lid in mod.get('contains_lessons', mod.get('lesson_ids', [])):
                original_mapping[lid] = mod['module_id']
        new_mapping = {}
        for mod in module_assignments:
            for lid in mod.get('lesson_ids', []):
                new_mapping[lid] = mod['module_id']
        data['_modules_changed'] = (original_mapping != new_mapping)

        data['lesson_list']           = lessons
        data['module_assignments']    = module_assignments
        data['_resume_requested']     = True
        st.rerun()

    if data.get('_resume_requested'):
        data['_resume_requested'] = False
        with st.spinner("Finalizing course structure..."):
            gen                = data['generator']
            lesson_list_run    = data['lesson_list']
            module_assignments = data['module_assignments']
            safe_title         = re.sub(r'[^a-zA-Z0-9_\-]', '_', data['title'])
            output_path        = f"data/courses/{safe_title}.json"

            result = asyncio.run(
                gen.resume_after_review(
                    lesson_list=lesson_list_run,
                    module_assignments=module_assignments,
                    output_path=output_path,
                    modules_changed=data.get('_modules_changed', False)
                )
            )

        data['result'] = result
        data['stats']  = {}
        if not result.get('success', True):
            st.error(f"Generation failed. Check terminal for details.")
        else:
            st.session_state.generator_v5_state = 'DONE'
            st.rerun()
    else:
        st.caption(f"**Structure:** {len(lessons)} lessons · {module_count} modules  ↓ Inspect below")
    st.markdown("---")


    # ── Scrollable lesson list ─────────────────────────────────────────────
    expand_all = st.session_state.get('module_review_expand_all', False)
    col_toggle, _ = st.columns([2, 8])
    with col_toggle:
        if st.button("↕ Expand All", use_container_width=True):
            st.session_state['module_review_expand_all'] = not expand_all
            st.rerun()

    with st.container(height=500, border=False, key="module_review"):
        module_num = 1
        for i, lesson in enumerate(lessons):
            lid    = lesson.get('lesson_id') or lesson.get('topic_id', '?')
            topic  = lesson.get('lesson_topic') or lesson.get('topic_title', lid)
            header = lesson.get('lesson_header', '') or lesson.get('header', '')
            sources = lesson.get('lesson_sources', lesson.get('source_ids', []))

            if i == 0 or is_boundary(lid):
                suggested_title = module_titles.get(lid, f"Module {module_num}")
                st.markdown(f"""
                <div class="module-header">
                    MODULE {module_num} — {suggested_title.upper()}
                </div>
                """, unsafe_allow_html=True)
                module_num += 1

            col_check, col_content = st.columns([0.5, 11])

            with col_check:
                if i == 0:
                    st.markdown("<div style='padding-top:8px'> </div>", unsafe_allow_html=True)
                else:
                    st.checkbox(
                        "New module",
                        key=f"boundary_{lid}",
                        label_visibility="collapsed",
                        help="Check to start a new module here"
                    )

            with col_content:
                with st.expander(f"**{lid}** · {topic}", expanded=expand_all):
                    if header:
                        st.markdown(f"##### {header}")
                    for pid in sources:
                        text = master_index.get(pid, '')
                        if text:
                            st.caption(f"{pid}: {text}")

# ========================================
# SCREEN 5: COMPLETION
# ========================================

def show_completion(view_container):
    """Completion screen: shows generation stats (time, lessons, modules, cost, tokens),
    download button, and options to open in Mastery Lab or generate another course."""
    if not st.session_state.get('_balloons_shown'):
        st.balloons()
        st.session_state['_balloons_shown'] = True
    
    # Class: completion-header, completion-icon
    st.markdown(
        "<h2 class='completion-header'>"
        "<span class='material-icons completion-icon'>check_circle</span> "
        "Course Generated!</h2>", 
        unsafe_allow_html=True
    )
    
    result    = st.session_state.generator_v5_data.get('result', {})
    stats     = st.session_state.generator_v5_data.get('stats', {})
    generator = st.session_state.generator_v5_data.get('generator')

    # Read counts from json_data if available, fall back to loading from file
    final_lessons_count = 0
    final_modules_count = 0

    json_data = result.get('json_data')
    if not json_data and result.get('json_path'):
        try:
            with open(result['json_path'], 'r', encoding='utf-8') as f:
                json_data = json.load(f)
        except Exception:
            json_data = {}

    if json_data:
        final_lessons_count = sum(
            1 for v in json_data.values()
            if isinstance(v, dict) and v.get('type') == 'lesson'
        )
        seen_modules = {
            v.get('module_id') for v in json_data.values()
            if isinstance(v, dict) and v.get('module_id')
        }
        final_modules_count = len(seen_modules)
    
    try:
        adapter_stats = generator.adapter.get_stats() if generator else {}
        raw_cost = adapter_stats.get('cost', 0)
        cost_str = adapter_stats.get('cost_formatted', 'N/A') if raw_cost > 0 else 'N/A'
    except Exception:
        adapter_stats = {}
        cost_str = 'N/A'

    tok_in  = adapter_stats.get('input_tokens', 0)
    tok_out = adapter_stats.get('output_tokens', 0)

    gen_start = st.session_state.generator_v5_data.get('generation_start_time')
    total_minutes = (time.time() - gen_start) / 60 if gen_start else result.get('time_elapsed', 0)

    st.markdown(f"""
    <div class="generator-stat-box">
        <div class="stat-item">
            <div class="stat-label">TIME</div>
            <div class="stat-value">{total_minutes:.1f} min</div>
        </div>
        <div class="stat-item-bordered">
            <div class="stat-label">LESSONS</div>
            <div class="stat-value">{final_lessons_count}</div>
        </div>
        <div class="stat-item-bordered">
            <div class="stat-label">MODULES</div>
            <div class="stat-value">{final_modules_count}</div>
        </div>
        <div class="stat-item-bordered">
            <div class="stat-label">COST</div>
            <div class="stat-value-success">{cost_str}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="generator-stat-box" style="margin-top:8px;">
        <div class="stat-item">
            <div class="stat-label">TOKENS IN</div>
            <div class="stat-value">{tok_in:,}</div>
        </div>
        <div class="stat-item-bordered">
            <div class="stat-label">TOKENS OUT</div>
            <div class="stat-value">{tok_out:,}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    
    st.divider()
    
    c_btn1, c_btn2 = st.columns(2)
    
    with c_btn1:
        if result and 'json_path' in result:
            try:
                with open(result['json_path'], 'r', encoding='utf-8') as f:
                    json_str = f.read()
                st.download_button(
                    label="Download JSON file",
                    icon=":material/download:",
                    data=json_str,
                    file_name=Path(result['json_path']).name,
                    mime="application/json",
                    use_container_width=True
                )
            except Exception:
                st.error("File read error.")

    with c_btn2:
        if st.button("Open in Mastery Lab", icon=":material/school:", type="primary", use_container_width=True):
            view_container.empty()
            time.sleep(0.2)
            from src.core.tutor import SimpleTutor
            if result and 'json_path' in result:
                json_path = result['json_path']
                
                st.session_state.tutor = SimpleTutor(json_path)
                st.session_state.current_course_path = json_path

                # Full generator wipe so nothing bleeds into tutor view
                st.session_state.generator_v5_state = None
                st.session_state.generator_v5_data = _fresh_generator_data()
                st.session_state.pop('_balloons_shown', None)
                st.session_state['_scroll_top'] = True
                st.rerun()
    
    if st.button("Generate Another Course", icon=":material/refresh:", type="secondary", use_container_width=True):
        st.session_state.generator_v5_state = 'INPUT'
        st.session_state.generator_v5_data = _fresh_generator_data()
        st.session_state.pop('_balloons_shown', None)
        st.rerun()

# ========================================
# UTILITIES
# ========================================

def _scroll_to_top(trigger=False, position=120, delay=150):
    """Always render to prevent DOM shifts, but execute scroll with a delay if triggered."""
    if trigger:
        js = f"""
        <script>
            // Cache bust: {time.time()}
            setTimeout(function() {{
                var body = window.parent.document.querySelector('section[data-testid="stMain"]');
                if (body) {{ 
                    body.scrollTo({{
                        top: {position}, 
                        behavior: 'smooth'
                    }}); 
                }}
            }}, {delay}); 
        </script>
        """
    else:
        js = ""
        
    components.html(js, height=0)

def _fresh_generator_data() -> dict:
    """Return a blank generator data dict. Single source of truth for resets."""
    return {
        'title': '',
        'source_text': '',
        'model_id': '',
        'current_step': 0,
        'progress': 0,
        'message': 'Initiation...',
        'stats': {},
        'logs': [],
        'lesson_list': [],
        'module_suggestion': {},
        'module_boundaries': [],
        'qc_data': None
    }

