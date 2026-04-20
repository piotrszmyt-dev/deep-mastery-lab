# src/prompt_templates.py
DEFAULT_PRESET_NAME = "Factory Default"

"""
PROMPT TEMPLATES MODULE
-----------------------
This module manages the construction of prompts for the AI Tutor.
It combines:
1. Immutable Technical Rules (Markdown structure, LaTeX placement, JSON formatting)
2. User-Defined Styles (Pedagogy, Language, Tone)
3. Content Instructions (Handling Raw Data vs Context)
"""

def get_current_language():
    """
    Get current language with session-state priority.
    
    Reads from session_state first (fast, always current),
    falls back to disk only on first load.
    """
    import streamlit as st
    
    # Priority 1: Session state (already in memory)
    if hasattr(st, 'session_state') and 'custom_language' in st.session_state:
        lang = st.session_state.custom_language
        if lang and isinstance(lang, str) and lang.strip():
            return lang
    
    # Priority 2: Disk (only on first load)
    try:
        from src.managers.settings_manager import SettingsManager
        settings = SettingsManager()
        config = settings.load()
        return config.get('custom_language', 'English')
    except Exception as e:
        print(f"Warning: Could not load language: {e}")
        return 'English'

def get_full_prompts_from_preset(preset_dict):
    """
    Merge preset (presentation + synthesis) with hardcoded questions.
    
    This ensures custom_prompts always has all 3 required keys,
    even though presets only store 2 customizable ones.
    
    Args:
        preset_dict: Dictionary with 'presentation' and 'synthesis' keys
    
    Returns:
        Complete dict with all 3 keys: presentation, synthesis, questions
    """
    return {
        'presentation': preset_dict.get('presentation', DEFAULT_USER_PROMPTS['presentation']),
        'synthesis': preset_dict.get('synthesis', DEFAULT_USER_PROMPTS['synthesis']),
        'questions': '',  # not user-customizable — handled by system prompt
    }
    
# ==============================================================================
# 2. DEFAULT STYLES - PEDAGOGICAL BASELINE
# ==============================================================================
# These are the default prompts used if the user hasn't customized anything.

DEFAULT_CUSTOMIZABLE_STYLE = {
    "presentation": """
ROLE: You are a clear, engaging educator.

APPROACH:
- Start with motivation (why this matters)
- Build from simple to complex (Bloom's progression)
- Use concrete examples with real numbers
- Connect new concepts to familiar ideas

STRUCTURE:
### Context & Motivation
### Core Concepts
### Deep Understanding
### Examples & Applications
### Connections & Comparisons
### Common Issues
    """,
    
    "synthesis": """
=== YOUR TEACHING STYLE ===

APPROACH:
- Write a warm, flowing recap of what the student just completed
- Highlight the big ideas — not exhaustive detail
- Celebratory tone: this is a milestone, not a drill
- No comparisons, no decision trees — just confident synthesis
    """,
    
    "final_test_card": """
"""
    
}

# Backward compatibility for app.py
DEFAULT_USER_PROMPTS = DEFAULT_CUSTOMIZABLE_STYLE.copy()

# Preset system constants
DEFAULT_PRESET_NAME = "Factory Default"

DEFAULT_PRESETS = {
    DEFAULT_PRESET_NAME: DEFAULT_CUSTOMIZABLE_STYLE.copy()
}



# ==============================================================================
# 3. BUILD LOGIC - THE RENDER ENGINE
# ==============================================================================

def build_final_prompt(mode, user_style, context_content, count=None, special_instructions=None):
    """
    Constructs a robust 'Sandwich' prompt for lessons, synthesis, or questions.

    Args:
        mode: 'presentation', 'synthesis', or 'questions'
        user_style: User's custom prompt override (or None for defaults)
        context_content: Source material
    """
    language = get_current_language()
    if isinstance(context_content, dict):
        primary = context_content.get('primary', '')
        prior_lessons = context_content.get('prior', [])
        future_lessons = context_content.get('future', [])
        lesson_title = context_content.get('title', '')
    else:
        primary = context_content
        prior_lessons = []
        future_lessons = []
        lesson_title = ''
    # 1. IMMUTABLE CORE - Mode-specific technical constraints
    if mode == 'questions':
        tech_constraints = f""" You are preparing multiple choice questions about "{lesson_title}"  that will be used for spaced repetition software. 
Write {count} standalone factual questions (never refer to “the lesson”, “the text”, or any source document) from the 4 key facts found in <primary_source>. The question must be standalone so it can be used for spaced repetition programs. 

Follow these rules:

CRITICAL SYSTEM INSTRUCTIONS:
1. LANGUAGE: Generate ALL output strictly in {language}.
2. OUTPUT FORMAT: Pure JSON array ONLY.
- NO markdown code blocks, NO preamble, NO trailing commas
3. CORRECT ANSWER: Always place correct answer as option "A".
- Python will randomize order later — do NOT pre-randomize.
4. Distractors can be drawn from <prior_context> and <upcoming_lessons>.
5. COUNT: Generate exactly {count} standalone questions.
"""
    else:
        tech_constraints = """
    CRITICAL SYSTEM INSTRUCTIONS:
    1. FORMAT: Use pure Markdown.
    2. MATH: ALL formulas, variables, and numbers with units MUST be LaTeX.
       - Correct: $I = 5A$, $U = 230V$, $R = 10\\Omega$
       - Incorrect: I = 5A, 5 Amperes
    3. LANGUAGE: Generate ALL output strictly in {language}.
    """.format(language=language)

    # 2. SOURCE MATERIAL (The "Truth")
    # We wrap content in XML tags so the model clearly sees where data begins/ends.
    if mode == 'questions':
        if prior_lessons:
            prior_xml = "\n".join(
                f'## {l["title"]}\n{l["content"]}\n\n'
                for l in prior_lessons
            )
            prior_section = f"""Prior lessons the student has already completed:
        <prior_lessons>
        {prior_xml}
        </prior_lessons>"""
        else:
            prior_section = ""

        if future_lessons:
            future_xml = "\n".join(f'## {l["title"]}\n{l["content"]}\n\n' for l in future_lessons)
            future_section = f"""Upcoming lessons for context only:
        <upcoming_lessons>
        {future_xml}
        </upcoming_lessons>"""
        else:
            future_section = ""

        data_block = f"""
        {prior_section}

        Primary lesson to generate standalone questions from:
        <primary_lesson>
        {primary}
        </primary_lesson>

        {future_section}

        {f'''<special_requests>
        {special_instructions}
        </special_requests>''' if special_instructions and special_instructions.strip() else ''}

        <json_structure>
        REQUIRED OUTPUT FORMAT — return a JSON array of exactly this shape:
        [
          {{
            "question": "Standalone question text in {language}.",
            "options": {{
              "A": "Correct answer in {language}",
              "B": "Plausible but wrong in {language}",
              "C": "Plausible but wrong in {language}",
              "D": "Plausible but wrong in {language}"
            }}
          }}
        ]
        </json_structure>
        """
    elif mode == 'synthesis':
        data_block = f"""
        <source_material>
        {primary}
        </source_material>
        """
    else:
        # Presentation mode
        if prior_lessons:
            prior_xml = "\n".join(
                f'## {l["title"]}\n{l["content"]}\n\n'
                for l in prior_lessons
            )
            prior_section = f"""The student already completed these lessons. Connect to them where it adds clarity — do NOT re-teach. Use them to show how the current content builds on what the student already knows.

        <prior_lessons>
        {prior_xml}
        </prior_lessons>"""
        else:
            prior_section = "This is the FIRST lesson. No prior knowledge assumed."

        if future_lessons:
            future_xml = "\n".join(f'## {l["title"]}\n{l["content"]}\n\n' for l in future_lessons)
            future_section = f"""The following lessons come after this one. Use this to show WHY the current lesson matters — what it unlocks, what problems it enables solving, how it will be directly applied. Weave this relevance naturally into the lesson. Do NOT teach, summarize, or preview the upcoming content.

        <upcoming_lessons>
        {future_xml}
        </upcoming_lessons>"""
        else:
            future_section = ""

        data_block = f"""
        {prior_section}

        <primary_lesson>
        {primary}
        </primary_lesson>

        {future_section}

        COVERAGE REQUIREMENT: Every fact, number, and technical value from <primary_lesson> must appear in your output — these are exam-critical. Do not simplify or omit them.
        """

    # 3. USER PERSONA (The "Vibe") — presentation and synthesis only
    if mode != 'questions':
        if not user_style or not user_style.strip():
            user_style = DEFAULT_CUSTOMIZABLE_STYLE.get(mode, "")
        teaching_style_block = f"""
    <teaching_style>
    {user_style}
    </teaching_style>
"""
    else:
        teaching_style_block = ""

    # 4. FINAL ASSEMBLY
    if mode == 'questions':
        task_instruction = f"Output exactly {count} standalone questions as a JSON array. Language: {language}."
    elif mode == 'synthesis':
        task_instruction = f"Write a recap of the lessons in <source_material> in {language}. Follow your teaching style."
    else:
        task_instruction = f"Generate the lesson in {language}. Priority: cover every fact and number from <primary_lesson> completely. Use <prior_lessons> to connect to what the student already knows. Use <upcoming_lessons> to motivate WHY this lesson matters. Follow your teaching style."

    final_prompt = f"""
    {tech_constraints}

    {data_block}
{teaching_style_block}
    <output_instruction>
    {task_instruction}
    </output_instruction>
    """
    _dump_debug_prompt(mode, final_prompt)
    return final_prompt

def _dump_debug_prompt(mode, prompt):
    """Overwrite debug file with latest prompt for this mode."""
    import os
    os.makedirs("data/debug/last_prompts", exist_ok=True)
    names = {
        'presentation':  'last_presentation_prompt.txt',
        'synthesis':     'last_synthesis_prompt.txt',
        'questions':     'last_question_prompt.txt',
    }
    filename = names.get(mode)
    if not filename:
        return
    try:
        with open(f"data/debug/last_prompts/{filename}", 'w', encoding='utf-8') as f:
            f.write(f"MODE: {mode}\n{'='*60}\n\n{prompt}")
    except Exception:
        pass

def build_final_card_prompt(course_outline: str) -> str:
    """
    Build the congratulations card prompt for FINAL_TEST.
    Not user-customizable — system prompt only.
    """
    language = get_current_language()
    return f"""
CRITICAL SYSTEM INSTRUCTIONS:
1. FORMAT: Pure Markdown. Use headers, bold, and emoji generously.
2. LANGUAGE: Generate ALL output strictly in {language}.
3. TONE: Warm, celebratory, and genuinely encouraging.

<course_outline>
{course_outline}
</course_outline>

The student has just completed every lesson, checkpoint, and module in the course above.

Write a congratulations message that:
1. Opens with a celebratory header acknowledging they've reached the end
2. Briefly summarize what they learned
3. Reflects warmly on how much knowledge they've gained and how exciting this journey was
4. Connects what they learned to real daily-life value and practical impact
5. Invites them to take the Final Test as the ultimate proof of their mastery
6. Closes with a genuine good luck wish

Keep it personal, energetic, and human. This is a milestone moment.
Generate the message in {language}.
"""