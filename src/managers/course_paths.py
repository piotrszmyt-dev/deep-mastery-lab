"""
Course Paths
============
Single source of truth for all dynamic course file paths.

Why this module exists
----------------------
Two managers — CacheManager and ProgressManager — both need to resolve
paths to the same per-course directory. Without a shared helper, each
manager would independently hardcode the directory structure, creating
two problems:

1. Drift: if the path convention changes (e.g. renaming `course_data/`),
   it must be updated in multiple places and it's easy to miss one.

2. Inconsistency: each manager previously used a different layout
   (cache/ and progress/ as separate sibling dirs), making it impossible
   to atomically delete all files for a single course.

Centralising path resolution here means:
- One place to update if the layout ever changes
- Both managers are guaranteed to point at the same directory
- Deleting a course's data is a single rmtree call

Directory layout
----------------
data/
  courses/          ← static syllabus files (JSON), never touched here
  course_data/
    <course_stem>/
      <stem>_cards.json
      <stem>_questions.json
      <stem>_progress.pkl
      <stem>_metrics.pkl
"""

from pathlib import Path

# Root directory for all generated per-course data
COURSE_DATA_ROOT = Path("data/course_data")


def get_course_dir(course_filename: str) -> Path:
    """
    Return (and create if needed) the directory for a course's dynamic files.

    Args:
        course_filename: Course filename or path, e.g. "python_basics.json"

    Returns:
        Path to data/course_data/<stem>/
    """
    stem = Path(course_filename).stem
    course_dir = COURSE_DATA_ROOT / stem
    course_dir.mkdir(parents=True, exist_ok=True)
    return course_dir


def get_cards_path(course_filename: str) -> Path:
    """Return path to the generated lesson cards cache file."""
    stem = Path(course_filename).stem
    return get_course_dir(course_filename) / f"{stem}_cards.json"


def get_questions_path(course_filename: str) -> Path:
    """Return path to the generated question pool cache file."""
    stem = Path(course_filename).stem
    return get_course_dir(course_filename) / f"{stem}_questions.json"


def get_progress_path(course_filename: str) -> Path:
    """Return path to the course progress file (current position, passed elements)."""
    stem = Path(course_filename).stem
    return get_course_dir(course_filename) / f"{stem}_progress.pkl"


def get_metrics_path(course_filename: str) -> Path:
    """Return path to the course metrics file (token usage, cost, time)."""
    stem = Path(course_filename).stem
    return get_course_dir(course_filename) / f"{stem}_metrics.pkl"


def get_media_path(course_filename: str) -> Path:
    """Return path to the media index file."""
    stem = Path(course_filename).stem
    return get_course_dir(course_filename) / f"{stem}_media.json"


def get_media_dir(course_filename: str) -> Path:
    """Return (and create if needed) the media files directory."""
    media_dir = get_course_dir(course_filename) / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir