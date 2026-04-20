"""
SRS Engine
==========
Pure FSRS wrapper. No I/O, no Streamlit. Converts dicts to Card objects,
applies one review, converts back to dicts for storage in SQLite.

Rating map (binary — no Hard/Easy granularity):
    Correct answer  → Rating.Good
    Wrong answer    → Rating.Again

Key FSRS property relied on here: a card with high stability that lapses
is NOT scheduled for tomorrow. Its new interval is proportional to its
former stability, so a card studied a year ago and then failed lands
at ~7–14 days, not 1 day. This is default FSRS behaviour — no special-casing needed.
"""

from fsrs import Scheduler, Card, Rating, State
from datetime import datetime, timezone

_scheduler = Scheduler(learning_steps=(), relearning_steps=())


# ============================================================================
# CONVERSION HELPERS
# ============================================================================

def _card_from_dict(d: dict) -> Card:
    """Restore a Card from a stored dict (SQLite row or new_card_dict)."""
    card = Card()
    if not d:
        return card
    try:
        if d.get('state') is not None:
            card.state = State(int(d['state']))
        if d.get('step') is not None:
            card.step = int(d['step'])
        stab = d.get('stability')
        if stab is not None:
            card.stability = float(stab)
        diff = d.get('difficulty')
        if diff is not None:
            card.difficulty = float(diff)
        lr = d.get('last_review')
        if lr:
            card.last_review = datetime.fromisoformat(lr).replace(tzinfo=timezone.utc)
        due = d.get('due')
        if due:
            card.due = datetime.fromisoformat(due).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        pass
    return card


def _card_to_dict(card: Card) -> dict:
    """Serialize a Card to a plain dict ready for SQLite insertion."""
    return {
        'due':         card.due.isoformat() if card.due else datetime.now(timezone.utc).isoformat(),
        'stability':   card.stability,
        'difficulty':  card.difficulty,
        'step':        card.step,
        'state':       card.state.value,
        'last_review': card.last_review.isoformat() if card.last_review else None,
    }


# ============================================================================
# PUBLIC API
# ============================================================================

def review_card(card_dict: dict, was_correct: bool) -> dict:
    """
    Apply one FSRS review.

    Args:
        card_dict: Current card fields as a dict (from DB or new_card_dict()).
        was_correct: True for correct answer (Rating.Good), False for wrong (Rating.Again).

    Returns:
        Updated card fields dict with new 'due', 'stability', 'step', etc.
    """
    card   = _card_from_dict(card_dict)
    rating = Rating.Good if was_correct else Rating.Again
    updated, _ = _scheduler.review_card(card, rating)
    return _card_to_dict(updated)


def new_card_dict() -> dict:
    """Return an empty card dict for a brand-new SRS entry (State.New)."""
    return _card_to_dict(Card())
