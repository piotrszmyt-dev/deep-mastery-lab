"""
Media Manager
=============
Manages supplementary media attachments per lesson.

Storage layout:
    data/course_data/<stem>/<stem>_media.json   — index of all media items
    data/course_data/<stem>/media/              — image files

Media item shapes:
    {"type": "image", "path": "media/L09_20260408.png"}   — local file
    {"type": "image", "url":  "https://..."}               — external image
    {"type": "link",  "url":  "https://...", "label": ""}  — external link
    {"type": "text",  "content": "Note text"}              — plain text note
"""

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from src.managers.course_paths import get_media_path, get_media_dir

_lock = threading.Lock()


# ============================================================================
# LOAD / SAVE
# ============================================================================

def load_media(course_filename: str) -> dict:
    path = get_media_path(course_filename)
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_media(course_filename: str, data: dict) -> None:
    """Atomic write — always called inside _lock."""
    path = get_media_path(course_filename)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


# ============================================================================
# READ
# ============================================================================

def get_lesson_media(course_filename: str, lesson_id: str) -> list:
    """Return media items for a lesson, empty list if none."""
    return load_media(course_filename).get(lesson_id, [])


# ============================================================================
# WRITE
# ============================================================================

def add_media_item(course_filename: str, lesson_id: str, item: dict) -> None:
    with _lock:
        data = load_media(course_filename)
        data.setdefault(lesson_id, []).append(item)
        _save_media(course_filename, data)


def remove_media_item(course_filename: str, lesson_id: str, index: int) -> None:
    with _lock:
        data = load_media(course_filename)
        items = data.get(lesson_id, [])
        if 0 <= index < len(items):
            removed = items.pop(index)
            # Delete local image file if present
            if removed.get('type') == 'image' and 'path' in removed:
                img_path = get_media_dir(course_filename).parent / removed['path']
                if img_path.exists():
                    img_path.unlink(missing_ok=True)
            if not items:
                data.pop(lesson_id, None)
            else:
                data[lesson_id] = items
            _save_media(course_filename, data)


# ============================================================================
# IMAGE FILE STORAGE
# ============================================================================

def save_image(course_filename: str, lesson_id: str, image_data, suffix: str = '.png') -> str:
    """
    Save image to media folder. Returns path relative to course_data/<stem>/ dir.

    Args:
        image_data: PIL Image (from paste) or bytes (from file upload)
        suffix: file extension including dot, e.g. '.png', '.jpg'

    Returns:
        Relative path string, e.g. "media/L09_20260408_143022.png"
    """
    media_dir = get_media_dir(course_filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:19]
    filename = f"{lesson_id}_{timestamp}{suffix}"
    path = media_dir / filename

    if hasattr(image_data, 'save'):   # PIL Image
        image_data.save(path, 'PNG')
    else:                              # bytes
        path.write_bytes(image_data)

    return f"media/{filename}"
