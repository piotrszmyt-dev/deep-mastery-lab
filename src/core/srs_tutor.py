"""
SRS Tutor
=========
Sibling of tutor.py. In contrast to SimpleTutor which navigates inside a
single course, SrsTutor specialises in navigating across all courses via
a flat list of due cards.

State machine (stored in self.state):
    SRS_TEST         — answering the current batch
    SRS_FEEDBACK     — batch results screen
    SRS_JOURNEY_CARD — journey: reading a lesson card for a wrong answer
    SRS_JOURNEY_TEST — journey: 1-question mini-test for a lesson
    SRS_JOURNEY_DONE — journey: completion screen

This object is stored in st.session_state.srs_tutor and is entirely
independent of SimpleTutor / the loaded course.
"""

import copy
import json
import math
import random
from pathlib import Path
from src.core.generators import build_lesson_source


def _interleave(queue: list) -> list:
    """
    Shuffle then spread cards so same-lesson questions are maximally apart.

    FSRS schedules all cards from a lesson at similar intervals, so without
    interleaving a batch could be dominated by one lesson even after shuffling.

    Algorithm:
      1. Shuffle globally for true randomness.
      2. Group by (course_name, lesson_id) — each group is already in random order.
      3. Round-robin pick one card from each group in turn.

    Result: consecutive cards always come from different lessons, while the
    within-lesson and cross-lesson order remains random.
    """
    from collections import defaultdict
    random.shuffle(queue)

    groups: dict = defaultdict(list)
    for item in queue:
        key = (item.get('course_name', ''), item.get('lesson_id', ''))
        groups[key].append(item)

    result = []
    group_lists = list(groups.values())
    while group_lists:
        next_round = []
        for g in group_lists:
            result.append(g.pop(0))
            if g:
                next_round.append(g)
        group_lists = next_round
    return result


class SrsTutor:
    """
    Queue walker for SRS review sessions.

    Args:
        queue:      Enriched due-card list from srs_manager.get_due_cards().
                    Each item is a dict with at minimum:
                        course_name, block_id, lesson_id, question (dict)
        batch_size: How many cards to show per batch (default 20).
    """

    def __init__(self, queue: list, batch_size: int = 20):
        self.queue       = _interleave(list(queue))
        self.batch_size  = batch_size
        self.batch_start = 0
        self.idx         = 0
        self.state       = "SRS_TEST"
        self._syllabi: dict = {}

    # -------------------------------------------------------------------------
    # Batch navigation
    # -------------------------------------------------------------------------

    @property
    def current_batch(self) -> list:
        return self.queue[self.batch_start: self.batch_start + self.batch_size]

    def current_card(self) -> dict:
        batch = self.current_batch
        return batch[self.idx] if self.idx < len(batch) else {}

    def advance(self) -> None:
        self.idx += 1

    def is_batch_done(self) -> bool:
        return self.idx >= len(self.current_batch)

    def has_next_batch(self) -> bool:
        return self.batch_start + self.batch_size < len(self.queue)

    def start_next_batch(self) -> None:
        self.batch_start += self.batch_size
        self.idx = 0
        self.state = "SRS_TEST"

    @property
    def batch_number(self) -> int:
        return self.batch_start // self.batch_size + 1

    @property
    def total_batches(self) -> int:
        return math.ceil(len(self.queue) / self.batch_size) if self.queue else 1

    @property
    def remaining_due(self) -> int:
        return max(0, len(self.queue) - self.batch_start - self.batch_size)

    # -------------------------------------------------------------------------
    # Session state loading
    # -------------------------------------------------------------------------

    def load_batch_into_session(self, session_state) -> None:
        """
        Push the current batch questions into st.session_state.
        Each question gets '_srs_meta' embedded for recording in feedback.
        """
        letters = ['A', 'B', 'C', 'D']
        questions = []
        for item in self.current_batch:
            q = copy.deepcopy(item.get("question", {}))
            if "_srs_meta" not in q:
                q["_srs_meta"] = {
                    "course_name": item["course_name"],
                    "block_id":    item["block_id"],
                    "lesson_id":   item["lesson_id"],
                }
            # Re-shuffle answer positions so correct letter varies each session
            correct_text = q['options'].get(q.get('correct', 'A'), '')
            texts = [q['options'][l] for l in letters]
            random.shuffle(texts)
            q['options'] = {l: t for l, t in zip(letters, texts)}
            for l, t in q['options'].items():
                if t == correct_text:
                    q['correct'] = l
                    break
            questions.append(q)

        session_state.questions            = questions
        session_state.answers              = [None] * len(questions)
        session_state.current_question_idx = 0

    # -------------------------------------------------------------------------
    # Cross-course data access (used by srs_journey.py)
    # -------------------------------------------------------------------------

    def get_lesson(self, course_name: str, lesson_id: str) -> dict:
        """Lazy-load and return the syllabus entry for lesson_id from course_name."""
        if course_name not in self._syllabi:
            path = Path("data/courses") / course_name
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._syllabi[course_name] = json.load(f)
            except Exception:
                self._syllabi[course_name] = {}
        elem = self._syllabi[course_name].get(lesson_id, {})
        if elem and not elem.get('lesson_source'):
            master_index = self._syllabi[course_name].get('_master_index', {})
            elem['lesson_source'] = build_lesson_source(elem, master_index)
        return elem

    def get_card_content(self, course_name: str, lesson_id: str):
        """Return cached AI card content for lesson_id, or None."""
        stem = Path(course_name).stem
        path = Path("data/course_data") / stem / f"{stem}_cards.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get(lesson_id)
        except Exception:
            return None

    def get_question_pool(self, course_name: str, lesson_id: str) -> list:
        """Return the question pool for lesson_id, or []."""
        stem = Path(course_name).stem
        path = Path("data/course_data") / stem / f"{stem}_questions.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get(lesson_id, {}).get("pool", [])
        except Exception:
            return []
