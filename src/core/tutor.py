"""
Tutor
=====
Lightweight state holder that tracks the user's position within a course.

A course is a flat dict (syllabus.json) where each element has a 'next' pointer,
forming a linked list. SimpleTutor walks this list one step at a time, holding
two pieces of state: current_id (which element the user is on) and state
(which UI screen to render).

Element types in the syllabus:
    lesson              — standard lesson card + test
    module_checkpoint   — mid-module check: AI-generated card + test drawn from
                          all lessons in the module so far
    module_synthesis    — end-of-module review: AI-generated card + test, no
                          question pool of its own
    final_test          — end of course: AI-generated congratulations card,
                          then a test drawn from the entire course

State machine:
    SimpleTutor holds the state string but does NOT enforce transitions.
    The render layer sets tutor.state directly to drive the UI.

    Normal learn flow:
        CARD → TEST → FEEDBACK → CARD (next element)
                              ↘ FINAL_TEST (end of course)

    Mastery mode (range test across selected lessons):
        CARD → MASTERY_SETUP → MASTERY_TEST → MASTERY_FEEDBACK
                                            ↘ MASTERY_JOURNEY_CARD (if failures)

    Mastery journey (revisit each failed lesson):
        MASTERY_JOURNEY_CARD → MASTERY_JOURNEY_TEST → MASTERY_JOURNEY_CARD (next)
                                                     ↘ MASTERY_JOURNEY_DONE (all done)
        MASTERY_JOURNEY_DONE → MASTERY_SETUP (retry) | CARD (exit)

    Mastery states are managed entirely by the mastery render files
    (mastery_render.py, mastery_mode_test_render.py, mastery_journey_render.py).
    SimpleTutor is unaware of their internal logic — it only stores the string.

SimpleTutor itself never renders anything — it is a pure data object.
app.py reads .state to decide which render function to call, and reads
.current_id to know which element is active.
"""

import json
from typing import Dict
from src.config.constants import DEFAULT_TEST_COUNTS
from src.core.generators import build_lesson_source


class SimpleTutor:
    """
    Holds the active position and UI state for one course session.

    Attributes:
        syllabus    (dict): Full course graph loaded from syllabus.json.
                            Keys are element IDs, values are element dicts
                            with at least 'next' and 'type' fields.
        current_id  (str):  ID of the element currently being shown.
                            Set to 'FINAL_TEST' at the end of the course.
        state       (str):  Current UI state. Valid values:
                                'CARD'                 — show lesson/synthesis/checkpoint card
                                'TEST'                 — show test for current element
                                'FEEDBACK'             — show post-test feedback
                                'MASTERY_SETUP'        — show mastery lesson selector
                                'MASTERY_TEST'         — show mastery range test
                                'MASTERY_FEEDBACK'     — show mastery test results
                                'MASTERY_JOURNEY_CARD' — show journey lesson card
                                'MASTERY_JOURNEY_TEST' — show journey lesson test
                                'MASTERY_JOURNEY_DONE' — show journey completion screen
    """
    
    def __init__(self, syllabus_json: str):
        """Load syllabus from disk and set position to the first element in CARD state."""

        with open(syllabus_json, 'r', encoding='utf-8') as f:
            self.syllabus = json.load(f)

        master_index = self.syllabus.get('_master_index', {})
        for elem in self.syllabus.values():
            if isinstance(elem, dict) and elem.get('type') == 'lesson' and not elem.get('lesson_source'):
                elem['lesson_source'] = build_lesson_source(elem, master_index)

        self.current_id = list(self.syllabus.keys())[0]
        self.state = 'CARD'

    def get_current_element(self) -> Dict:
        """Return the syllabus entry for the current element."""
        return self.syllabus[self.current_id]
    
    def get_next_element_id(self) -> str:
        """Return the ID of the element following the current one, or 'FINAL_TEST'."""
        return self.syllabus[self.current_id]['next']
    
    def move_to_next(self) -> str:
        """
        Advance to the next element and update state accordingly.

        If the next element is FINAL_TEST, sets state to 'TEST' immediately.
        The FINAL_TEST renders an AI-generated congratulations card followed
        by a course-wide test — both handled in learn_card_render.py.
        Otherwise sets state to 'CARD' for the new element.

        Returns:
            The new current_id after advancing.
        """
        next_id = self.get_next_element_id()
        
        if next_id == 'FINAL_TEST':
            self.current_id = 'FINAL_TEST'
            self.state = 'TEST' 
            return 'FINAL_TEST'
        
        self.current_id = next_id
        self.state = 'CARD'
        return next_id

    def get_test_count(self, custom_settings=None) -> int:
        """
        Return the number of questions for the current element's test.

        Looks up the element's type in custom_settings first, then falls back
        to DEFAULT_TEST_COUNTS from constants.py.

        Args:
            custom_settings: Dict of element_type → question_count overrides, e.g.
                            {'lesson': 3, 'final_test': 30}
        """
        settings = custom_settings or {}
        if self.current_id == 'FINAL_TEST':
            element_type = 'final_test'
        else:
            element_type = self.get_current_element().get('type', 'lesson')
        return settings.get(element_type, DEFAULT_TEST_COUNTS.get(element_type, 5))