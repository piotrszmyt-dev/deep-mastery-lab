"""
Cache Manager
=============
Manages two on-disk caches per course:
- Lesson cards  (*_cards.json)     — generated card content keyed by element ID
- Question pools (*_questions.json) — generated question pools with random sampling

Both files live under data/course_data/<stem>/ via course_paths.py.

Design principles:
- Generate once, sample many times
- Fast repeat tests via random sampling
- Simple = maintainable
"""

import copy
import json
import os
import random
import tempfile
import threading
import streamlit as st

_pool_write_lock = threading.Lock()
_card_write_lock  = threading.Lock()   # shared with prefetch_manager
from datetime import datetime
from src.managers.course_paths import get_cards_path, get_questions_path
from src.utils.logger import get_logger

_log_cards = get_logger("cards")
_log_questions = get_logger("questions")

# ============================================================================
# CARD CONTENT CACHE
# ============================================================================

def get_cache_path(course_filename):
    """Returns path to the lesson cards cache file."""
    return get_cards_path(course_filename)


def save_cache_to_disk(course_filename):
    """Save lesson card cache for a course from RAM to disk.

    Merges session state with existing disk content under _card_write_lock
    so background prefetch writes are never overwritten by a main-thread save.
    Prefetch cards land on disk first; this merge preserves them while adding
    any cards the main thread generated.
    """
    if course_filename not in st.session_state.content_cache:
        return
    path = get_cache_path(course_filename)
    with _card_write_lock:
        existing = {}
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception as e:
                _log_cards.warning("save_cache_to_disk merge-read failed course=%s: %s", course_filename, e)
        merged = {**existing, **st.session_state.content_cache[course_filename]}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)


def remove_card_cache(course_filename, element_id):
    """Remove a single card from both memory cache and disk.

    Used by regenerate — save_cache_to_disk merges from disk and would
    resurrect a just-deleted entry, so we need a direct delete instead.
    """
    if course_filename in st.session_state.content_cache:
        st.session_state.content_cache[course_filename].pop(element_id, None)

    path = get_cache_path(course_filename)
    with _card_write_lock:
        if not path.exists():
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if element_id not in data:
                return
            del data[element_id]
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _log_cards.warning("remove_card_cache failed course=%s element=%s: %s",
                               course_filename, element_id, e)


def load_cache_from_disk(course_filename):
    """
    Load lesson card cache from disk into RAM.

    Returns:
        bool: True if loaded successfully, False if file missing or unreadable.
    """
    path = get_cache_path(course_filename)
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                st.session_state.content_cache[course_filename] = data
                return True
        except Exception as e:
            _log_cards.error("load cards cache failed course=%s: %s", course_filename, e)
    return False

def clear_cards_cache(course_filename: str) -> bool:
    """Clear only the generated lesson cards for a course."""
    if course_filename in st.session_state.content_cache:
        del st.session_state.content_cache[course_filename]
    path = get_cache_path(course_filename)
    if path.exists():
        path.unlink()
        return True
    return False

# ============================================================================
# QUESTION POOL CACHE
# ============================================================================

def get_question_cache_path(course_filename):
    """Returns path to the question pool cache file."""
    return get_questions_path(course_filename)

def load_question_pools(course_filename):
    """
    Load all question pools for a course.
    
    Returns:
        dict: {element_id: {"pool": [...], "generated_at": "..."}}
    """
    path = get_question_cache_path(course_filename)
    
    if not path.exists():
        return {}
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        _log_questions.error("load question pools failed course=%s: %s", course_filename, e)
        return {}


def save_question_pools(course_filename, pools_data):
    """Save all question pools for a course (atomic write)."""
    path = get_question_cache_path(course_filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(pools_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        _log_questions.error("save question pools failed course=%s: %s", course_filename, e)


def get_pool(course_filename, element_id):
    """
    Get question pool for element.
    
    Returns:
        list: Question pool or None if doesn't exist
    """
    pools = load_question_pools(course_filename)
    entry = pools.get(element_id)
    
    if entry and 'pool' in entry:
        return entry['pool']
    
    return None

def save_pool(course_filename, element_id, questions):
    """
    Save question pool for element.

    Args:
        course_filename: Course file name
        element_id: Element ID (e.g., "M1-C1a")
        questions: List of question dicts
    """
    with _pool_write_lock:
        pools = load_question_pools(course_filename)
        pools[element_id] = {
            'pool': questions,
            'generated_at': datetime.now().isoformat(),
            'pool_size': len(questions)
        }
        save_question_pools(course_filename, pools)

def clear_pool(course_filename, element_id):
    """
    Clear question pool for element.

    Use when user clicks "Regenerate" button.
    """
    with _pool_write_lock:
        pools = load_question_pools(course_filename)
        if element_id in pools:
            del pools[element_id]
            save_question_pools(course_filename, pools)
            return True
    return False

def clear_questions_cache(course_filename: str) -> bool:
    """Clear only the question pool for a course."""
    path = get_question_cache_path(course_filename)
    if path.exists():
        path.unlink()
        return True
    return False

def update_question_in_pool(course_filename, element_id, target_id, new_question_text, new_correct_text):
    """
    Update question text and correct-answer text for a single question in the pool.

    Matches by target_id. Only modifies the 'question' field and the correct
    option in 'options' — all other fields (correct letter, source_ids, etc.)
    are left untouched.

    Returns:
        True if the question was found and saved, False otherwise.
    """
    with _pool_write_lock:
        pools = load_question_pools(course_filename)
        entry = pools.get(element_id)
        if not entry:
            return False

        pool = entry.get('pool', [])
        updated = False
        for q in pool:
            if q.get('target_id') == target_id:
                q['question'] = new_question_text
                correct_letter = q.get('correct', 'A')
                q['options'][correct_letter] = new_correct_text
                updated = True
                break

        if not updated:
            return False

        pools[element_id] = {
            'pool': pool,
            'generated_at': entry.get('generated_at'),
            'pool_size': entry.get('pool_size', len(pool)),
        }
        save_question_pools(course_filename, pools)
    return True


def remove_question_from_pool(course_filename, element_id, question):
    """Remove a single question from the pool by target_id match.

    Matches by target_id rather than dict equality — the session question
    may have _srs_meta injected and reshuffled options, so full dict
    comparison always fails after a draw.
    """
    target_id = question.get('target_id', '')
    if not target_id:
        return False

    with _pool_write_lock:
        pools = load_question_pools(course_filename)
        entry = pools.get(element_id)
        if not entry:
            return False

        pool = entry.get('pool', [])
        new_pool = [q for q in pool if q.get('target_id') != target_id]

        if len(new_pool) == len(pool):
            return False  # nothing matched

        pools[element_id] = {
            'pool': new_pool,
            'generated_at': entry.get('generated_at'),
            'pool_size': len(new_pool)
        }
        save_question_pools(course_filename, pools)
    return True

def _reshuffle_options(questions: list) -> list:
    """
    Deep-copy questions and re-shuffle answer option positions.

    Called at every draw so the correct answer lands at a different letter
    each session — prevents positional memorisation across repeated reviews.
    Works on any stored state: correct may already be A, B, C, or D.
    """
    letters = ['A', 'B', 'C', 'D']
    result = []
    for q in questions:
        q = copy.deepcopy(q)
        correct_text = q['options'].get(q.get('correct', 'A'), '')
        texts = [q['options'][l] for l in letters]
        random.shuffle(texts)
        q['options'] = {l: t for l, t in zip(letters, texts)}
        for l, t in q['options'].items():
            if t == correct_text:
                q['correct'] = l
                break
        result.append(q)
    return result


def sample_from_pool(pool, count):
    """
    Randomly sample questions from pool and re-shuffle answer positions.

    Args:
        pool: List of questions
        count: Number of questions needed

    Returns:
        list: Sampled questions with freshly randomised option positions
    """
    return _reshuffle_options(random.sample(pool, min(count, len(pool))))

def get_questions_for_test(course_filename, element_id, test_count,
                           generate_callback=None):
    """
    Get questions for a test — handles cache, generation, sampling.

    1. Checks if pool exists on disk.
    2. Generates if missing (via callback) — LLM decides question count.
    3. Samples randomly up to test_count.

    Args:
        course_filename: Course file name
        element_id: Element ID
        test_count: Max questions to show in the test (sampling cap)
        generate_callback: Function() → list, called if pool is missing

    Returns:
        list: Test questions (sampled from pool), or None if unavailable
    """
    pool = get_pool(course_filename, element_id)

    if not pool and generate_callback:
        pool = generate_callback()
        if pool:
            save_pool(course_filename, element_id, pool)

    if not pool:
        return None

    return sample_from_pool(pool, test_count)

# ============================================================================
# RANGE TEST SUPPORT
# ============================================================================

def get_questions_for_range(course_filename, element_ids, total_count):
    """
    Get questions from multiple elements for Test Mode.
    
    Args:
        course_filename: Course file name
        element_ids: List of element IDs
        total_count: Total questions needed
        
    Returns:
        list: Questions with 'source' field added
    """
    pools = load_question_pools(course_filename)
    ignored = st.session_state.get('ignored_elements', set())
    all_questions = []
    for elem_id in element_ids:
        if elem_id in pools:
            if elem_id in ignored:        
                continue
            pool = pools[elem_id].get('pool', [])
            # Add source tag
            for q in pool:
                q_copy = q.copy()
                q_copy['source'] = elem_id
                all_questions.append(q_copy)
    
    return _reshuffle_options(random.sample(all_questions, min(total_count, len(all_questions))))

def get_pool_stats(course_filename):
    """
    Get statistics about cached pools.
    
    Returns:
        dict: Statistics
    """
    pools = load_question_pools(course_filename)
    
    total_questions = sum(
        entry.get('pool_size', 0) 
        for entry in pools.values()
    )
    
    return {
        'total_pools': len(pools),
        'total_questions': total_questions,
        'elements': list(pools.keys()),
        'avg_pool_size': total_questions / len(pools) if pools else 0
    }


