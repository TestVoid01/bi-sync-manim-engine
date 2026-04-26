"""
Bi-Sync Runtime Provenance
==========================

Captures lightweight source provenance on every live Manim Mobject so the
selection system can resolve runtime objects back to AST source anchors.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import sys
from typing import Any, Optional

_CREATION_COUNTERS: dict[tuple[str, int], int] = defaultdict(int)
_TRACKED_SCENE_FILE: Optional[str] = None
_TRACKED_PROJECT_ROOT: Optional[str] = None
_PATCHED = False
_ORIGINAL_MOBJECT_INIT = None
_ORIGINAL_OPENGL_MOBJECT_INIT = None


def configure_tracking(
    scene_file: str | Path | None,
    *,
    project_root: str | Path | None = None,
) -> None:
    global _TRACKED_SCENE_FILE, _TRACKED_PROJECT_ROOT
    _TRACKED_SCENE_FILE = str(Path(scene_file).resolve()) if scene_file else None
    _TRACKED_PROJECT_ROOT = str(Path(project_root).resolve()) if project_root else None


def reset_creation_tracking() -> None:
    _CREATION_COUNTERS.clear()


def patch_manim_creation_tracking() -> None:
    global _PATCHED, _ORIGINAL_MOBJECT_INIT, _ORIGINAL_OPENGL_MOBJECT_INIT
    if _PATCHED:
        return

    from manim.mobject.mobject import Mobject
    from manim.mobject.opengl.opengl_mobject import OpenGLMobject

    _ORIGINAL_MOBJECT_INIT = Mobject.__init__
    _ORIGINAL_OPENGL_MOBJECT_INIT = OpenGLMobject.__init__

    def _patched_mobject_init(self: Any, *args: Any, **kwargs: Any) -> None:
        _ORIGINAL_MOBJECT_INIT(self, *args, **kwargs)
        _attach_runtime_provenance(self)

    def _patched_opengl_mobject_init(self: Any, *args: Any, **kwargs: Any) -> None:
        _ORIGINAL_OPENGL_MOBJECT_INIT(self, *args, **kwargs)
        _attach_runtime_provenance(self)

    Mobject.__init__ = _patched_mobject_init
    OpenGLMobject.__init__ = _patched_opengl_mobject_init
    _PATCHED = True


def _attach_runtime_provenance(mobject: Any) -> None:
    try:
        frame = sys._getframe(1)
        while frame:
            filename = frame.f_code.co_filename
            if _matches_source_frame(filename):
                resolved = str(Path(filename).resolve())
                line_number = frame.f_lineno
                occurrence = _next_occurrence(resolved, line_number)
                mobject._bisync_source_file = resolved
                mobject._bisync_line_number = line_number
                mobject._bisync_occurrence = occurrence
                break
            frame = frame.f_back
    except Exception:
        pass


def _matches_source_frame(filename: str) -> bool:
    if not filename or not filename.endswith(".py"):
        return False

    try:
        resolved = str(Path(filename).resolve())
    except Exception:
        resolved = filename

    if _TRACKED_SCENE_FILE is not None:
        return resolved == _TRACKED_SCENE_FILE

    if _TRACKED_PROJECT_ROOT and resolved.startswith(_TRACKED_PROJECT_ROOT):
        return True

    return False


def _next_occurrence(filename: str, line_number: int) -> int:
    key = (filename, line_number)
    _CREATION_COUNTERS[key] += 1
    return _CREATION_COUNTERS[key]
