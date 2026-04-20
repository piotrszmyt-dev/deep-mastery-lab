"""
Question Generator - Optimized & LLM-Friendly
==============================================
Streamlined question generation focused on:
- Clear, focused prompts
- Minimal post-processing
- Fast batch generation
- Python handles randomization
"""

import json
import re
import random
from typing import List, Dict, Optional
from src.core.prompt_templates import build_final_prompt
from src.utils.logger import get_logger

logger = get_logger("questions")
logger_raw = get_logger("questions_raw")


# ============================================================================
# MINIMAL CLEANING (Only What's Essential)
# ============================================================================

def _assign_metadata(questions: List[Dict], block_id: str) -> List[Dict]:
    """Assign target_id, source_ids, and correct — Python owns these, not the LLM."""
    for i, q in enumerate(questions):
        q['target_id'] = f"{block_id}_Q{i + 1:02d}"
        q['source_ids'] = [block_id]
        q['correct'] = 'A'
    return questions


def extract_json_from_response(text: str) -> Optional[str]:
    """Extract JSON from LLM response, handling common formats."""
    # 1. Try markdown code block
    json_block = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL | re.IGNORECASE)
    if json_block:
        return json_block.group(1)
    
    # 2. Try raw JSON array
    json_array = re.search(r'(\[\s*\{.*?\}\s*\])', text, re.DOTALL)
    if json_array:
        return json_array.group(1)
    
    # 3. Assume entire response is JSON
    return text.strip()


def parse_and_validate_json(response_text: str, expected_count: int = None) -> Optional[List[Dict]]:
    """
    Parse JSON and validate structure.
    
    ONLY validates:
    - Valid JSON
    - List of objects
    - Required keys present
    
    Does NOT validate:
    - Content quality (trust the prompt)
    - Source accuracy (trust the prompt)
    - Difficulty (trust the prompt)
    """
    json_str = extract_json_from_response(response_text)
    
    # Fix trailing commas (common LLM error)
    json_str = re.sub(r',\s*([\]\}])', r'\1', json_str)
    
    try:
        questions = json.loads(json_str)
        
        if not isinstance(questions, list):
            return None
        
        if len(questions) == 0:
            return None
        
        valid_questions = []
        for q in questions:
            if not all(k in q for k in ['question', 'options']):
                continue
            if not isinstance(q['options'], dict) or not all(k in q['options'] for k in ['A','B','C','D']):
                continue
            valid_questions.append(q)
        
        if not valid_questions:
            return None
        if expected_count and len(valid_questions) < expected_count:
            logger.warning("Incomplete pool: got %d questions, expected %d", len(valid_questions), expected_count)
            return None
        return valid_questions[:expected_count] if expected_count else valid_questions
    
        
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parsing error: {e}")
        return None
    except Exception as e:
        logger.warning(f"Validation error: {e}")
        return None

# ============================================================================
# RANDOMIZATION (Python Does This, Not LLM)
# ============================================================================

def shuffle_question_options(questions: List[Dict]) -> List[Dict]:
    """
    Shuffle answer options by reassigning letter labels.
    LLM always puts correct answer as 'A' — we randomize which letter it ends up at.
    """
    letters = ['A', 'B', 'C', 'D']
    for q in questions:
        correct_letter = q.get('correct', 'A')
        correct_text = q['options'].get(correct_letter, q['options'].get('A', ''))

        # Collect all texts and shuffle
        texts = [q['options'][l] for l in letters]
        random.shuffle(texts)

        # Reassign letters to shuffled texts
        q['options'] = {l: t for l, t in zip(letters, texts)}

        # Find which letter now holds the correct text
        for l, t in q['options'].items():
            if t == correct_text:
                q['correct'] = l
                break
    
    return questions

# ============================================================================
# MAIN GENERATION FUNCTION (Streamlined)
# ============================================================================

def generate_test_questions(
    card_content: str,
    adapter=None,
    custom_instruction: str = None,
    block_id: str = 'UNKNOWN',
    count: int = None,
    max_retries: int = 2,
    special_instructions: str = None,
) -> Optional[List[Dict]]:
    """
    Generate test questions for a lesson.

    Args:
        card_content: Source material for questions (dict with primary/prior, or str)
        adapter: API adapter
        custom_instruction: Optional custom style/requirements
        block_id: Paragraph ID (e.g. 'P045') — Python assigns target_id/source_ids from this
        count: Expected total question count (used for cap and task instruction)
        max_retries: Maximum retry attempts (default: 2)

    Returns:
        List of question dicts or None if failed
    """
    prompt = build_final_prompt(
        mode='questions',
        user_style=custom_instruction,
        context_content=card_content,
        count=count,
        special_instructions=special_instructions,
    )
    for attempt in range(max_retries):
        try:
            raw_result = adapter.generate(prompt, generation_type='Quiz')

            usage = raw_result.get('usage') if isinstance(raw_result, dict) else None
            response = raw_result.get('content', '') if isinstance(raw_result, dict) else raw_result

            questions = parse_and_validate_json(response, expected_count=count)

            if questions:
                _assign_metadata(questions, block_id)
                return questions

            logger.warning("Parse failed, retry %d/%d", attempt + 1, max_retries)
            logger_raw.warning(
                "Parse failed (attempt %d/%d)\nUsage : %s\nContent (%d chars):\n%s\n%s",
                attempt + 1, max_retries,
                usage,
                len(response), "-" * 60, response,
            )

        except Exception as e:
            logger.error(f"Generation error (attempt {attempt + 1}): {e}")

    logger.error(f"Failed to generate questions after {max_retries} attempts")
    return None




