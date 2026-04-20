from pathlib import Path

def get_available_courses():
    """
    Get list of available course files from data/courses directory.
    
    Returns:
        list: List of course filenames (.json files)
    """
    path = Path("data/courses")
    return [f.name for f in path.glob("*.json")] if path.exists() else []