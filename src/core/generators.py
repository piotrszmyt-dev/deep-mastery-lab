"""
Generation Wrappers
-------------------
Unified entry points for all AI content generation in the LMS layer.

Functions:
    generate_card_content         — Presentation or synthesis card, foreground or prefetch
    get_raw_context_data          — Extracts lesson_content + optional prior-lesson context
    generate_questions_background — Test questions in background threads (thread-safe)
    generate_final_card           — Congratulations card for FINAL_TEST completion

Design principles:
    - All calls go through ThreadSafeTrackingAdapter for automatic cost tracking
    - Adapter-agnostic: works with any adapter exposing .generate(prompt, model, max_tokens)
    - Mode detection (presentation vs synthesis) is handled here, not by the caller
    - Context injection (prior lessons) is resolved here before the prompt is built
"""

import json

from src.core.prompt_templates import build_final_prompt
from src.core.question_generator import generate_test_questions
from src.api.usage_tracking import ThreadSafeTrackingAdapter
from src.core.prompt_templates import build_final_card_prompt

FUTURE_CONTEXT_DEPTH = 2  # upcoming lessons shown to AI for context (hardcoded)


def build_lesson_source(elem: dict, master_index: dict) -> str:
    """Reconstruct lesson_source from element fields and master_index.

    Replaces the stored lesson_source field — all inputs already exist
    in the syllabus element and _master_index, so storing the derived
    string is redundant.
    """
    lines = []
    if elem.get('module_title'):
        lines.append(f"**Module:** {elem['module_title']}\n")
    if elem.get('lesson_header'):
        lines.append(f"**Source Header:** {elem['lesson_header']}\n")
    if elem.get('lesson_title'):
        lines.append(f"**Lesson Title:** {elem['lesson_title']}")
    lines.append('')
    for pid in elem.get('source_ids', []):
        text = master_index.get(pid, '').strip()
        if text:
            lines.append(text)
            lines.append('')
    return '\n'.join(lines).strip()

def _serialize_lesson_content(lesson_content, master_index=None, module_title='', lesson_title=''):
    """
    Format lesson_content list into prompt-ready text.
    Text is pulled from master_index — not stored in lesson_content.

    Output format:
        ### Module Title: ...
        ### Lesson Title: ...

        #### source_id: P044
        #### Generate 5 questions
        P044: full paragraph text...

        #### source_id: P045
        #### Generate 3 questions
        P045: full paragraph text...
    """
    if master_index is None:
        master_index = {}

    # Handle both new format (list) and old format (dict with 'blocks')
    if isinstance(lesson_content, dict):
        blocks = lesson_content.get('blocks', [])
        if not blocks:
            return ''
        # Old format: reconstruct title from 'title' field
        if not module_title and not lesson_title:
            title_parts = [p.strip() for p in lesson_content.get('title', '').split('|')]
            if len(title_parts) >= 2:
                module_title = title_parts[0]
                lesson_title = title_parts[-1]
            elif title_parts:
                lesson_title = title_parts[0]
    elif isinstance(lesson_content, list):
        blocks = lesson_content
        if not blocks:
            return ''
    else:
        return ''

    lines = []
    if module_title:
        lines.append(f"### Module Title: {module_title}")
    if lesson_title:
        lines.append(f"### Lesson Title: {lesson_title}")
    if lines:
        lines.append('')

    for block in blocks:
        bid = block.get('id', '')
        if 'text' not in block:
            # New format: {id, questions} — pull text from master_index
            text = master_index.get(bid, '').strip()
            if not text:
                continue
            q_count = block.get('questions', 0)
            if q_count:
                lines.append(f"#### Generate {q_count} standalone questions")
            lines.append(text)
            lines.append('')

    return '\n'.join(lines).rstrip()

# ============================================================================
# CARD CONTENT GENERATION
# ============================================================================

def generate_card_content(
    syllabus,
    element_id,
    adapter,
    model_id,
    user_prompt,
    course_filename=None, 
    context_window: int = 0 
):
    """
    Generate card content for a single syllabus element.

    Automatically selects mode based on element type:
        - 'lesson'                          → 'presentation' mode
        - 'module_synthesis' / 'module_checkpoint' → 'synthesis' mode

    Used by both the background prefetch pipeline and foreground manual regeneration.

    Args:
        syllabus (dict): Full course syllabus dictionary.
        element_id (str): ID of the element to generate content for (e.g. 'L01a').
        adapter: API adapter instance — any object exposing .generate(prompt, model, max_tokens).
        model_id (str): Model identifier string (e.g. 'google/gemini-2.5-flash-lite').
        user_prompt (str): User's custom style instruction for this generation mode.
        course_filename (str, optional): Course filename for usage/cost tracking.
                                         If None, generation proceeds without tracking.
        context_window (int): Number of prior lessons to inject as context.
                              0 disables context injection. Default 0.

    Returns:
        str: Generated markdown content, or None if element_id not found in syllabus.
    
    Example:
        >>> content = generate_card_content(
        ...     syllabus=tutor.syllabus,
        ...     element_id="L01a",
        ...     adapter=adapter,
        ...     model_id="google/gemini-2.5-flash-lite",
        ...     user_prompt=custom_prompts['presentation'],
        ...     course_filename="electronics_101.pkl",
        ...     context_window=2
        ... )
    """
    # Validate element exists
    elem = syllabus.get(element_id)
    if not elem:
        print(f"[WARN] Element {element_id} not found in syllabus")
        return None

    # Prepare context data based on element type
    elem_type = elem.get('type', '')
    mode = 'synthesis' if elem_type in ('module_synthesis', 'module_checkpoint') else 'presentation'
    context_data = get_raw_context_data(syllabus, element_id, context_window, mode=mode)
    final_prompt = build_final_prompt(mode, user_prompt, context_data)

    if course_filename:
        safe_adapter = ThreadSafeTrackingAdapter(adapter, model_id, course_filename, element_id=element_id)
        result = safe_adapter.generate(final_prompt)
    else:
        # Direct generation without tracking (rare, mainly for testing)
        result = adapter.generate(final_prompt, model=model_id)
    
    # Extract content from response
    # API returns dict with 'content' and 'usage' keys
    if isinstance(result, dict):
        return result.get('content', '')
    return result


def get_raw_context_data(syllabus, element_id, context_window: int = 0, mode: str = 'questions', future_window: int = FUTURE_CONTEXT_DEPTH):
    """
    Extract lesson content and optional prior-lesson context for card generation.

    For regular lessons, walks the syllabus backwards via 'next' pointer reversal
    to collect up to context_window preceding lessons. Non-lesson elements in the
    chain (checkpoints, syntheses) are skipped in the result but traversal continues.

    For module_synthesis and module_checkpoint elements, combines all children
    lesson content instead — prior context is not applicable and is always empty.

    Args:
        syllabus (dict): Full course syllabus dictionary.
        element_id (str): ID of the element to generate content for.
        context_window (int): Maximum number of prior lessons to collect. Default 0.

    Returns:
        dict:
            'primary' (str):  lesson_content of the target element, or combined
                              children content for synthesis/checkpoint types.
            'prior'   (list): Up to context_window prior lessons, oldest first.
                              Each entry is a dict with keys: 'id', 'title', 'content'.
                              Empty list if context_window=0 or element is first in chain.
    """
    elem = syllabus.get(element_id)
    if not elem:
        return {'primary': '', 'prior': [], 'future': []}

    elem_type = elem.get('type', '')

    # Synthesis/checkpoint: combine children, no prior context needed
    if elem_type in ('module_synthesis', 'module_checkpoint'):
        master_index = syllabus.get('_master_index', {})
        parts = []
        for child_id in elem.get('children_ids', []):
            child = syllabus.get(child_id, {})
            lesson_title = child.get('lesson_title', child_id)
            texts = [master_index.get(pid, '').strip() for pid in child.get('source_ids', [])]
            prose = '\n'.join(t for t in texts if t)
            parts.append(f"### {lesson_title}\n{prose}")
        return {'primary': '\n\n'.join(parts), 'prior': [], 'future': []}

    # Build reverse lookup: element_id → previous_element_id
    prior = []
    if context_window > 0:
        next_to_prev = {}
        for eid, edata in syllabus.items():
            if not isinstance(edata, dict):
                continue
            nxt = edata.get('next')
            if nxt:
                next_to_prev[nxt] = eid

        cursor = element_id
        while len(prior) < context_window:
            prev_id = next_to_prev.get(cursor)
            if not prev_id:
                break
            prev_elem = syllabus.get(prev_id, {})
            if prev_elem.get('type') == 'lesson':
                master_index = syllabus.get('_master_index', {})
                texts = [master_index.get(pid, '').strip() for pid in prev_elem.get('source_ids', [])]
                content = '\n'.join(t for t in texts if t)
                prior.append({
                    'id': prev_id,
                    'title': prev_elem.get('lesson_title', prev_id),
                    'content': content
                })
            cursor = prev_id

        prior.reverse()  # oldest first

    # Forward walk: collect up to future_window upcoming lessons
    # Treats the course as a continuous string — skips checkpoints/syntheses but
    # continues traversal through them. Stops at FINAL_TEST or end of chain.
    future = []
    if future_window > 0:
        cursor = element_id
        while len(future) < future_window:
            next_id = syllabus.get(cursor, {}).get('next')
            if not next_id or next_id == 'FINAL_TEST':
                break
            next_elem = syllabus.get(next_id, {})
            if next_elem.get('type') == 'lesson':
                master_index = syllabus.get('_master_index', {})
                texts = [master_index.get(pid, '').strip() for pid in next_elem.get('source_ids', [])]
                content = '\n'.join(t for t in texts if t)
                future.append({
                    'id': next_id,
                    'title': next_elem.get('lesson_title', next_id),
                    'content': content,
                })
            cursor = next_id

    primary = (
        build_lesson_source(elem, syllabus.get('_master_index', {}))
        if mode == 'presentation'
        else _serialize_lesson_content(
            elem.get('lesson_content', []),
            master_index=syllabus.get('_master_index', {}),
            module_title=elem.get('module_title', ''),
            lesson_title=elem.get('lesson_title', '')
        )
    )
    return {'primary': primary, 'prior': prior, 'future': future, 'title': elem.get('lesson_title', '')}

# ============================================================================
# QUESTION GENERATION
# ============================================================================

def generate_questions_background(
    card_content,
    adapter,
    model_id,
    prompt_instruction,
    course_filename,
    block_id,
    count=None,
    element_id=None,
    special_instructions=None,
):
    """
    Generate test questions in a background thread (thread-safe).

    Thin wrapper around generate_test_questions that injects a
    ThreadSafeTrackingAdapter for automatic cost tracking. Intended for
    use in the prefetch pipeline where questions are generated in parallel
    with card display.

    Args:
        card_content (str): Raw lesson content to generate questions from.
                            Should be lesson_content from syllabus, not AI-generated card text.
        count (int): Number of questions to generate.
        adapter: API adapter instance — any object exposing .generate(prompt, model, max_tokens).
        model_id (str): Model identifier string (e.g. 'google/gemini-2.5-flash-lite').
        prompt_instruction (str): User's custom instruction for question style.
        course_filename (str): Course filename for usage/cost tracking.
        element_id (str, optional): Element ID used as a label in tracking logs. Default None.

    Returns:
        list[dict]: List of question dictionaries, each with keys:
                    - 'text'        (str):  Question text
                    - 'options'     (list): Four answer option strings
                    - 'correct'     (str):  Correct answer letter — 'A', 'B', 'C', or 'D'
                    - 'explanation' (str):  Explanation of why the answer is correct
    
    Example:
        >>> questions = generate_questions_background(
        ...     card_content=lesson_text,
        ...     count=5,
        ...     adapter=adapter,
        ...     model_id="google/gemini-2.5-flash-lite",
        ...     prompt_instruction=custom_prompts['questions'],
        ...     course_filename="electronics_101.pkl",
        ...     element_id='L03b'
        ... )
    """
    # Wrap adapter with thread-safe tracker for background task
    safe_adapter = ThreadSafeTrackingAdapter(adapter, model_id, course_filename, element_id=element_id)
    
    # Delegate to the actual question generator
    return generate_test_questions(
        card_content,
        adapter=safe_adapter,
        custom_instruction=prompt_instruction,
        block_id=block_id,
        count=count,
        special_instructions=special_instructions,
    )

# ============================================================================
# FINAL CARD GENERATION
# ============================================================================

def generate_final_card(syllabus: dict, adapter, model_id: str, course_filename: str = None) -> str:
    """
    Generate the congratulations card shown at FINAL_TEST completion.

    Scans the syllabus to build a structured course outline (modules → lessons),
    then passes it to build_final_card_prompt and calls the API.

    Args:
        syllabus (dict): Full course syllabus dictionary.
        adapter: API adapter instance — any object exposing .generate(prompt, model, max_tokens).
        model_id (str): Model identifier string.
        course_filename (str, optional): Course filename for usage/cost tracking.
                                         If None, generation proceeds without tracking.

    Returns:
        str: Generated congratulations card as markdown text.
             Empty string if the API returns an empty response.
    """

    # Build outline: group lessons under their modules
    lines = []
    seen_modules = {}
    for eid, elem in syllabus.items():
        if not isinstance(elem, dict):
            continue
        etype = elem.get('type', '')
        if etype == 'lesson':
            mod_title = elem.get('module_title', 'Unknown Module')
            if mod_title not in seen_modules:
                seen_modules[mod_title] = []
            seen_modules[mod_title].append(elem.get('lesson_title', eid))

    for mod_title, lessons in seen_modules.items():
        lines.append(f"**{mod_title}**")
        for lt in lessons:
            lines.append(f"  - {lt}")

    course_outline = "\n".join(lines)
    prompt = build_final_card_prompt(course_outline)

    if course_filename:
        safe_adapter = ThreadSafeTrackingAdapter(adapter, model_id, course_filename, element_id='FINAL_TEST')
        result = safe_adapter.generate(prompt, generation_type='FinalCard')
        return result.get('content', '') if isinstance(result, dict) else result
    else:
        result = adapter.generate(prompt, model=model_id)
        return result.get('content', '') if isinstance(result, dict) else result