"""
Prefetch Manager
================
Generates cards and question pools ahead of the user's current position,
saving everything to disk so the next card and test are ready instantly —
no waiting time when the user advances.

PREFETCH_DEPTH = 4
    How many lessons ahead to prefetch.
    For each lesson, card and questions are submitted as independent concurrent
    tasks — up to 8 threads in flight for normal mode, 4 for raw mode.

    Example: user is on L01 → pipeline targets L02, L03, L04, L05 simultaneously,
    submitting card + questions for each in one flat pass.

    run_prefetch_pipeline() is called on every CARD render. Tasks that are already
    on disk or in-flight are skipped silently. Tasks that previously failed (not on
    disk, not in-flight) are automatically resubmitted — no special retry logic needed.

Two modes
---------
Normal mode (raw_mode=False):
    Per element: card task + questions task, submitted concurrently and independently.
    module_synthesis and module_checkpoint: card task only (no question pool).

Raw mode (raw_mode=True):
    Questions only — no card generation for regular lessons.
    lesson_source is displayed directly as the "card".
    Exception: module_synthesis and module_checkpoint still need AI cards
    because they have no lesson_source to fall back on.

Thread safety
-------------
All disk writes use dedicated locks (_card_write_lock for cards,
_pool_write_lock in cache_manager for question pools).
No session_state is accessed inside threads — all values are captured
into plain dicts (card_params, q_params) before threads are spawned.
"""

import threading
import time
import json

from src.utils.logger import get_logger
from src.managers.cache_manager import (
    get_cache_path, get_pool, save_pool, _card_write_lock
)
from src.core.generators import generate_card_content, generate_final_card, get_raw_context_data
from src.managers.models_manager import resolve_model_id
from src.core.question_generator import generate_test_questions
from src.api.usage_tracking import ThreadSafeTrackingAdapter


PREFETCH_DEPTH = 4
STALE_FUTURE_AGE = 240  # seconds before an in-flight future is considered hung

_log_cards = get_logger("cards")
_log_questions = get_logger("questions")

# Module-level future tracking — accessible from threads, unlike session_state
# Structure: { element_id: {'card': Future|None, 'questions': Future|None} }
_futures: dict = {}
_futures_lock = threading.Lock()

# Submission timestamps for stale-future detection: { element_id: float (time.time()) }
_submit_times: dict = {}

# _card_write_lock imported from cache_manager — shared with save_cache_to_disk
# so main-thread and background-thread card writes are mutually exclusive.
_cancel_flag = threading.Event()


# =============================================================================
# DISK HELPERS
# =============================================================================

def is_card_on_disk(course_filename, element_id) -> bool:
    """Check whether card content for element_id exists in the on-disk cache.
    Reads the JSON file directly — safe to call from threads."""
    path = get_cache_path(course_filename)
    if not path.exists():
        return False
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return element_id in data
    except Exception as e:
        _log_cards.warning("is_card_on_disk read failed course=%s element=%s: %s", course_filename, element_id, e)
        return False


def save_card_to_disk(course_filename, element_id, content):
    """Thread-safe write of a single card entry to the shared JSON cache."""
    path = get_cache_path(course_filename)
    with _card_write_lock:
        data = {}
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                _log_cards.warning("save_card_to_disk load failed course=%s (starting fresh): %s", course_filename, e)
                data = {}
        data[element_id] = content
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def load_card_from_disk(course_filename, element_id):
    """Read a single card from disk. Returns None if not found."""
    path = get_cache_path(course_filename)
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f).get(element_id)
    except Exception as e:
        _log_cards.warning("load_card_from_disk failed course=%s element=%s: %s", course_filename, element_id, e)
        return None


# =============================================================================
# SYLLABUS WALKER
# =============================================================================

def walk_ahead(syllabus, current_id, depth) -> list:
    """Return up to `depth` element IDs following current_id in the syllabus.
    Includes FINAL_TEST when it is within range — it has a prefetchable
    congratulations card. Stops after FINAL_TEST since nothing follows it."""
    ids = []
    nid = syllabus.get(current_id, {}).get('next')
    for _ in range(depth):
        if not nid:
            break
        ids.append(nid)
        if nid == 'FINAL_TEST':
            break  # nothing follows FINAL_TEST
        nid = syllabus.get(nid, {}).get('next')
    return ids


# =============================================================================
# THREAD WORKERS
# =============================================================================

def _card_task(element_id, syllabus, adapter,
               course_filename, model_id, user_prompt, context_window: int = 0):
    """Thread: generate + save card content for element_id."""
    if _cancel_flag.is_set():
        return
    try:
        content = generate_card_content(
            syllabus, element_id, adapter, model_id, user_prompt, course_filename, context_window
        )
        if content and not _cancel_flag.is_set():
            save_card_to_disk(course_filename, element_id, content)
    except Exception as e:
        _log_cards.error("prefetch card failed element=%s: %s", element_id, e)
    finally:
        with _futures_lock:
            if element_id in _futures:
                _futures[element_id].pop('card', None)


def _final_test_card_task(syllabus, adapter, course_filename, model_id):
    """Thread: generate + save the FINAL_TEST congratulations card."""
    if _cancel_flag.is_set():
        return
    try:
        content = generate_final_card(syllabus, adapter, model_id, course_filename)
        if content and not _cancel_flag.is_set():
            save_card_to_disk(course_filename, 'FINAL_TEST', content)
    except Exception as e:
        _log_cards.error("prefetch final_test card failed: %s", e)
    finally:
        with _futures_lock:
            if 'FINAL_TEST' in _futures:
                _futures['FINAL_TEST'].pop('card', None)


def _questions_task(raw_context, element_id, course_filename,
                    syllabus, adapter, model_id, prompt_instruction):
    """Thread: generate + save question pool for element_id."""
    safe_adapter = ThreadSafeTrackingAdapter(adapter, model_id, course_filename, element_id=element_id)
    if _cancel_flag.is_set():
        return
    try:
        block_id = syllabus.get(element_id, {}).get('source_ids', ['UNKNOWN'])[0]
        _lc = syllabus.get(element_id, {}).get('lesson_content', [])
        count = _lc[0].get('questions') if _lc else None
        if not count:
            return
        questions = generate_test_questions(
            raw_context, adapter=safe_adapter,
            custom_instruction=prompt_instruction,
            block_id=block_id,
            count=count,
        )
        if questions and not _cancel_flag.is_set():
            save_pool(course_filename, element_id, questions)
    except Exception as e:
        _log_questions.error("prefetch questions failed element=%s: %s", element_id, e)
    finally:
        with _futures_lock:
            if element_id in _futures:
                _futures[element_id].pop('questions', None)


# =============================================================================
# SUBMISSION HELPERS
# =============================================================================

def prune_stale_futures():
    """Remove futures that are done or have been in-flight longer than STALE_FUTURE_AGE.

    Called at the start of each run_prefetch_pipeline. Frees tracking slots so
    elements whose threads hung can be resubmitted on the next render cycle.
    """
    now = time.time()
    with _futures_lock:
        stale = []
        for eid, tasks in _futures.items():
            age = now - _submit_times.get(eid, now)
            if all(f.done() for f in tasks.values()):
                stale.append(eid)
            elif age > STALE_FUTURE_AGE:
                _log_cards.warning("prefetch stale future pruned element=%s age=%.0fs", eid, age)
                stale.append(eid)
        for eid in stale:
            _futures.pop(eid, None)
            _submit_times.pop(eid, None)


def _maybe_submit_card(element_id, syllabus, adapter, executor,
                       course_filename, card_params):
    """Submit a card generation thread if not already cached or in-flight."""
    if is_card_on_disk(course_filename, element_id):
        return
    with _futures_lock:
        if 'card' in _futures.get(element_id, {}):
            return
        future = executor.submit(
            _card_task,
            element_id, syllabus, adapter,
            course_filename, card_params['model_id'], card_params['prompt'],
            card_params.get('context_window', 0)
        )
        _futures.setdefault(element_id, {})['card'] = future
        _submit_times[element_id] = time.time()


def _maybe_submit_questions(element_id, raw_context,
                             course_filename, syllabus, adapter, executor, q_params):
    """Submit a question generation thread if no pool exists and none is in-flight."""
    if get_pool(course_filename, element_id) is not None:
        return
    with _futures_lock:
        if 'questions' in _futures.get(element_id, {}):
            return
        future = executor.submit(
            _questions_task,
            raw_context, element_id, course_filename,
            syllabus, adapter, q_params['model_id'], q_params['prompt']
        )
        _futures.setdefault(element_id, {})['questions'] = future
        _submit_times[element_id] = time.time()


# =============================================================================
# Public API
# =============================================================================

def run_prefetch_pipeline(tutor, adapter, executor, course_filename,
                          selected_models, active_provider, custom_prompts,
                          context_window: int = 0,
                          raw_mode: bool = False):
    """
    Call this once per CARD render cycle. Non-blocking.

    Walks PREFETCH_DEPTH elements ahead and submits card + question generation
    as independent concurrent tasks for each element. All tasks are submitted in
    one flat pass — no chaining, no sequencing.

    Tasks already on disk or in-flight are skipped. Tasks that previously failed
    (not on disk, not in-flight) are resubmitted automatically on the next render.

    Normal mode: up to PREFETCH_DEPTH × 2 concurrent tasks (card + questions each).
    Raw mode:    up to PREFETCH_DEPTH concurrent tasks (questions only).
    module_synthesis / module_checkpoint: card only, no question pool.
    """
    prune_stale_futures()

    if not adapter:
        return

    future_ids = walk_ahead(tutor.syllabus, tutor.current_id, PREFETCH_DEPTH)
    if not future_ids:
        return

    def _card_params_for(element_id):
        elem = tutor.syllabus.get(element_id, {})
        mode = 'synthesis' if elem.get('type') in ('module_synthesis', 'module_checkpoint') else 'presentation'
        return {
            'model_id': resolve_model_id(active_provider, selected_models[mode]),
            'prompt': custom_prompts[mode],
            'context_window': context_window,
        }

    def _q_params_for():
        return {
            'model_id': resolve_model_id(active_provider, selected_models['questions']),
            'prompt': custom_prompts['questions'],
        }

    for eid in future_ids:
        elem = tutor.syllabus.get(eid, {})
        elem_type = elem.get('type', 'lesson')

        if elem_type == 'final_test':
            # Congratulations card — always generate, never in raw mode skip, no questions
            if not is_card_on_disk(course_filename, 'FINAL_TEST'):
                with _futures_lock:
                    if 'card' not in _futures.get('FINAL_TEST', {}):
                        model_id = resolve_model_id(active_provider, selected_models['presentation'])
                        future = executor.submit(
                            _final_test_card_task,
                            tutor.syllabus, adapter, course_filename, model_id,
                        )
                        _futures.setdefault('FINAL_TEST', {})['card'] = future
                        _submit_times['FINAL_TEST'] = time.time()
            continue

        is_summary_type = elem_type in ('module_synthesis', 'module_checkpoint')

        # Cards: always in normal mode; summaries need AI cards even in raw mode
        if not raw_mode or is_summary_type:
            _maybe_submit_card(eid, tutor.syllabus, adapter, executor,
                               course_filename, _card_params_for(eid))

        # Questions: regular lessons only (summaries have no question pool)
        if not is_summary_type:
            raw_context = get_raw_context_data(tutor.syllabus, eid, context_window)
            if raw_context.get('primary'):
                _maybe_submit_questions(eid, raw_context,
                                        course_filename, tutor.syllabus,
                                        adapter, executor, _q_params_for())


def clear_futures(element_id=None):
    """Call from full_reset(). Clears tracking without cancelling threads."""
    with _futures_lock:
        if element_id:
            _futures.pop(element_id, None)
        else:
            _futures.clear()


def cancel_and_reset():
    """Signal all running threads to abort, clear future tracking, then re-arm
    the cancel flag so the pipeline is ready for a new course."""
    _cancel_flag.set()
    with _futures_lock:
        _futures.clear()
        _submit_times.clear()
    _cancel_flag.clear()


def reset_at_module_boundary():
    """Lightweight reset at module checkpoint/synthesis boundaries.

    Clears all in-flight future tracking so any hung threads are forgotten and
    elements can be resubmitted fresh. Does NOT set the cancel flag — running
    threads are allowed to finish and write their results to disk.
    Called once per boundary crossing from learn_card_render.py.
    """
    with _futures_lock:
        count = len(_futures)
        _futures.clear()
        _submit_times.clear()
    if count:
        _log_cards.info("module boundary reset: cleared %d tracked futures", count)
