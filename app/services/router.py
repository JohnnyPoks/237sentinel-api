"""Content router (brief §4).

Detects what kind of thing the user submitted and which service should handle
it. The user never has to declare "this is an image or a video?" — this does it.
"""
from __future__ import annotations

import re

from app.schemas.analysis import ContentType

_URL_ONLY = re.compile(r"^\s*(https?://|www\.)\S+\s*$", re.I)

_EXT = {
    ContentType.image: {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"},
    ContentType.audio: {".mp3", ".wav", ".ogg", ".oga", ".m4a", ".opus", ".aac"},
    ContentType.video: {".mp4", ".mov", ".mkv", ".webm", ".avi", ".3gp"},
    ContentType.document: {".pdf", ".doc", ".docx"},
}

_MIME_PREFIX = {
    "image/": ContentType.image,
    "audio/": ContentType.audio,
    "video/": ContentType.video,
    "application/pdf": ContentType.document,
}


def detect_from_text(text: str) -> ContentType:
    """A bare URL is a link; anything else is text (it may contain URLs)."""
    if _URL_ONLY.match(text or ""):
        return ContentType.link
    return ContentType.text


def detect_from_file(filename: str | None, content_type: str | None) -> ContentType:
    ct = (content_type or "").lower()
    for prefix, kind in _MIME_PREFIX.items():
        if ct.startswith(prefix):
            return kind
    name = (filename or "").lower()
    dot = name.rfind(".")
    ext = name[dot:] if dot != -1 else ""
    for kind, exts in _EXT.items():
        if ext in exts:
            return kind
    # Unknown binary: treat as document so we at least try text extraction.
    return ContentType.document
