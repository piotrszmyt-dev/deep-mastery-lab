"""
Media Render
============
Renders supplementary media attachments for a lesson card,
and provides the add-media popover UI.

Public API:
    _media_render(course_filename, lesson_id)  — display existing items
    _media_add_popover(course_filename, lesson_id)  — add-new-item popover body
"""

import hashlib
import io
import streamlit as st
from pathlib import Path

from src.managers.media_manager import (
    get_lesson_media,
    add_media_item,
    remove_media_item,
    save_image,
)
from src.managers.course_paths import get_course_dir


# =============================================================================
# Display
# =============================================================================

def _media_render(course_filename: str, lesson_id: str, key_prefix: str = "card") -> None:
    """
    Render all supplementary media for a lesson.

    Shows nothing if there are no items.
    Each item gets a delete button (1-col) and its content (9-col).

    Args:
        key_prefix: Disambiguates widget keys when rendered in multiple locations
                    on the same page (e.g. "card" vs "popover").
    """
    items = get_lesson_media(course_filename, lesson_id)
    if not items:
        return

    st.markdown(":material/attach_file: **Supplementary Material**")

    course_dir = get_course_dir(course_filename)

    for i, item in enumerate(items):
        col_del, col_content = st.columns([1, 9])
        with col_del:
            if st.button(
                "",
                icon=":material/delete:",
                key=f"media_del_{key_prefix}_{lesson_id}_{i}",
                use_container_width=True,
                help="Remove this item",
            ):
                remove_media_item(course_filename, lesson_id, i)
                st.rerun()

        with col_content:
            _render_media_item(item, course_dir)


def _render_media_item(item: dict, course_dir: Path) -> None:
    item_type = item.get("type")

    if item_type == "image":
        if "path" in item:
            img_path = course_dir / item["path"]
            if img_path.exists():
                st.image(str(img_path))
            else:
                st.warning(f"Image file not found: {item['path']}")
        elif "url" in item:
            st.image(item["url"])

    elif item_type == "link":
        label = item.get("label") or item.get("url", "Link")
        url = item.get("url", "")
        if url:
            st.link_button(label, url)

    elif item_type == "text":
        content = item.get("content", "")
        if content:
            st.markdown(content)


# =============================================================================
# Add-media popover body
# =============================================================================

def _media_add_popover(course_filename: str, lesson_id: str) -> None:
    """
    Render the contents of the 'add media' popover.

    Sections (separated by dividers):
      1. Paste from clipboard (streamlit-paste-button)
      2. Upload image file
      3. Add external link
      4. Add text note
    """
    from streamlit_paste_button import paste_image_button  # lazy import — optional dep

    # ── 1. Paste ──────────────────────────────────────────────────────────────
    # Guard: paste_image_button retains image_data across reruns while the
    # popover is open, causing an infinite save→rerun loop without this check.
    st.caption("Paste from clipboard")
    paste_result = paste_image_button(
        "Paste Image",
        background_color="rgba(255,255,255,0.2)",
        hover_background_color="rgba(255,255,255,0.3)",
        text_color="rgba(255,255,255,0.5)",
        key=f"media_paste_{lesson_id}",
    )
    _paste_guard_key = f"_media_paste_guard_{lesson_id}"
    if paste_result.image_data:
        buf = io.BytesIO()
        paste_result.image_data.save(buf, format="PNG")
        img_hash = hashlib.md5(buf.getvalue()[:4096]).hexdigest()
        if st.session_state.get(_paste_guard_key) != img_hash:
            st.session_state[_paste_guard_key] = img_hash
            rel_path = save_image(course_filename, lesson_id, paste_result.image_data)
            add_media_item(course_filename, lesson_id, {"type": "image", "path": rel_path})
            st.rerun()
        # No else: guard must NOT be cleared on None — the component unmounts/remounts
        # during reruns (popover close→reopen) causing a brief None that would wipe the
        # guard and trigger a duplicate save on the next render.


    # ── 2. Upload ─────────────────────────────────────────────────────────────
    # Same guard: file_uploader can also persist across reruns inside a popover.
    st.caption("Upload image file")
    uploaded = st.file_uploader(
        "Upload image",
        type=["png", "jpg", "jpeg", "gif", "webp"],
        key=f"media_upload_{lesson_id}",
        label_visibility="collapsed",
    )
    _upload_guard_key = f"_media_upload_guard_{lesson_id}"
    if uploaded is not None:
        file_sig = f"{uploaded.name}:{uploaded.size}"
        if st.session_state.get(_upload_guard_key) != file_sig:
            st.session_state[_upload_guard_key] = file_sig
            suffix = Path(uploaded.name).suffix.lower() or ".png"
            rel_path = save_image(course_filename, lesson_id, uploaded.read(), suffix=suffix)
            add_media_item(course_filename, lesson_id, {"type": "image", "path": rel_path})
            st.rerun()
        # No else: same reason as paste guard — don't clear on None.


    # ── 3. External link ──────────────────────────────────────────────────────
    st.caption("Add external link")
    link_url = st.text_input(
        "URL", key=f"media_link_url_{lesson_id}", placeholder="https://..."
    )
    link_label = st.text_input(
        "Label (optional)", key=f"media_link_label_{lesson_id}"
    )
    if st.button(
        "Add Link",
        key=f"media_link_add_{lesson_id}",
        use_container_width=True,
        disabled=not link_url.strip(),
    ):
        add_media_item(
            course_filename,
            lesson_id,
            {"type": "link", "url": link_url.strip(), "label": link_label.strip()},
        )
        st.rerun()


    # ── 4. Text note ──────────────────────────────────────────────────────────
    st.caption("Add text note")
    note = st.text_area("Note", key=f"media_note_{lesson_id}", height=100, label_visibility="collapsed")
    if st.button(
        "Add Note",
        key=f"media_note_add_{lesson_id}",
        use_container_width=True,
        disabled=not note.strip(),
    ):
        add_media_item(course_filename, lesson_id, {"type": "text", "content": note.strip()})
        st.rerun()
