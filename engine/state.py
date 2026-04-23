"""
Bi-Sync Engine State — Future-Proof Socket Architecture
========================================================

Socket Map:
    Socket 1: on_scene_parsed()          — AST listener hook
    Socket 2: push_hitbox(id, bbox)      — Hit-testing data store
    Socket 3: request_render(dt)         — Paint trigger callback
    Socket 4: (in ASTMutator)            — Live bind mobject→code
    Socket 5: pause/resume_file_watcher  — Feedback loop prevention

Note: Atomic file writes are handled directly by ASTMutator.save_atomic().
No SSD debounce infrastructure needed — file watcher pauses during drag.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from engine.ast_mutator import ASTAnimationRef

logger = logging.getLogger("bisync.state")


class EngineState:
    """
    Central state manager for the Bi-Sync Manim Engine.

    Provides future-proof socket hooks that Phase 2 (AST Mutator)
    and Phase 3 (Canvas Controller) will plug into without modifying
    the Phase 1 rendering core.

    Safety:
        - All callbacks are wrapped in try/except to prevent
          a bad plugin from crashing the rendering pipeline.
        - File writes are handled directly by ASTMutator.save_atomic()
          (no SSD debounce infrastructure needed).
    """

    def __init__(self) -> None:
        # ── Socket 1: Scene Parsed Event ──
        # Phase 2 will attach its AST listener here to track
        # variable-to-mobject mappings when a new .py file loads.
        self._scene_parsed_callbacks: list[Callable[[], None]] = []

        # ── Socket 2: Hitbox Registry ──
        # Phase 3 will read this dict for mouse hit-testing.
        # Key: mobject_id (int), Value: AABB bounding box tuple
        # Format: (min_x, min_y, max_x, max_y) in Manim math coords
        self._hitboxes: dict[int, tuple[float, float, float, float]] = {}

        # ── Socket 3: Render Request Callback ──
        # Set by ManimCanvas to allow external code to trigger repaints.
        self._render_callback: Optional[Callable[[float], None]] = None

        # ── File Watcher Control (Socket 5) ──
        self._file_watcher_paused: bool = False

        # ── GUI Update Callbacks (State Reconciliation) ──
        self._gui_update_callbacks: list[Callable[[], None]] = []

        # ── Scene Health (Black Screen Trap Prevention) ──
        self.scene_is_healthy: bool = True

        # ── Phase 5: Selected Animation for Visual Editing ──
        self.selected_animation: Optional[ASTAnimationRef] = None

        # ── Phase 6: Deep Graphical Control (Selection Tracking) ──
        self._selected_mobject_name: Optional[str] = None
        self._selection_callbacks: list[Callable[[Optional[str]], None]] = []
        
        # Isolation Mode
        self.isolated_mobject_id: Optional[int] = None
        self.isolated_mobject_path: list[int] = []

        logger.info("EngineState initialized with 5 sockets")

    # ────────────────────────────────────────────────────────────
    # Socket 1: Scene Parsed
    # ────────────────────────────────────────────────────────────

    def on_scene_parsed(self, callback: Callable[[], None]) -> None:
        """Register a callback for when a Manim scene is parsed.

        Phase 2's AST Listener will use this to build the
        variable→Mobject mapping table.
        """
        self._scene_parsed_callbacks.append(callback)
        logger.debug(f"Registered scene_parsed callback: {callback.__name__}")

    def emit_scene_parsed(self) -> None:
        """Fire all scene_parsed callbacks. Called after Scene.construct()."""
        for cb in self._scene_parsed_callbacks:
            try:
                cb()
            except Exception as e:
                logger.error(f"scene_parsed callback {cb.__name__} failed: {e}")

    # ────────────────────────────────────────────────────────────
    # Socket 2: Hitbox Registry
    # ────────────────────────────────────────────────────────────

    def push_hitbox(
        self,
        mobject_id: int,
        bounding_box: tuple[float, float, float, float],
    ) -> None:
        """Store AABB bounding box for a rendered Mobject.

        Called by the renderer after each frame. Phase 3's
        Mouse Ray-Caster will query this for hit-testing.

        Args:
            mobject_id: Python id() of the Mobject
            bounding_box: (min_x, min_y, max_x, max_y) in Manim coords
        """
        self._hitboxes[mobject_id] = bounding_box

    def get_hitboxes(self) -> dict[int, tuple[float, float, float, float]]:
        """Return the current hitbox registry."""
        return self._hitboxes

    def clear_hitboxes(self) -> None:
        """Clear all hitboxes. Called at start of each frame."""
        self._hitboxes.clear()

    # ────────────────────────────────────────────────────────────
    # Socket 3: Render Request
    # ────────────────────────────────────────────────────────────

    def set_render_callback(self, callback: Callable[[float], None]) -> None:
        """Set the render trigger. ManimCanvas sets this to self.update()."""
        self._render_callback = callback
        logger.debug("Render callback registered")

    def request_render(self, dt: float = 0.0) -> None:
        """Request a new frame. Phase 2 calls this after code hot-swap."""
        if self._render_callback is not None:
            try:
                self._render_callback(dt)
            except Exception as e:
                logger.error(f"Render request failed: {e}")
        else:
            logger.warning("request_render called but no callback registered")

    # ────────────────────────────────────────────────────────────
    # File Watcher Control (Socket 5)
    # ────────────────────────────────────────────────────────────

    def pause_file_watcher(self) -> None:
        """Pause QFileSystemWatcher during continuous slider/drag operations.

        Socket 5 (Phase 2): Prevents feedback loop where:
        slider → file write → watcher → reload → slider → ∞
        """
        self._file_watcher_paused = True
        logger.debug("File watcher PAUSED")

    def resume_file_watcher(self) -> None:
        """Resume QFileSystemWatcher after drag/slider release."""
        self._file_watcher_paused = False
        logger.debug("File watcher RESUMED")

    @property
    def is_file_watcher_paused(self) -> bool:
        """Check if file watcher is currently paused."""
        return self._file_watcher_paused

    def set_file_watcher(self, watcher: Any) -> None:
        """Register the file watcher instance for Socket 5 control."""
        self._file_watcher = watcher
        logger.debug("File watcher registered with EngineState")

    # ────────────────────────────────────────────────────────────
    # GUI State Reconciliation
    # ────────────────────────────────────────────────────────────

    def on_gui_update(self, callback: Callable[[], None]) -> None:
        """Register a callback for GUI state reconciliation.

        Called when code changes externally and GUI sliders
        need to sync with the new code values.
        """
        self._gui_update_callbacks.append(callback)

    def emit_gui_update(self) -> None:
        """Fire all GUI update callbacks (State Reconciliation)."""
        for cb in self._gui_update_callbacks:
            try:
                cb()
            except Exception as e:
                logger.error(f"GUI update callback failed: {e}")

    # ────────────────────────────────────────────────────────────
    # Phase 6: Selection State Control
    # ────────────────────────────────────────────────────────────

    @property
    def selected_mobject_name(self) -> Optional[str]:
        return self._selected_mobject_name

    def set_selected_mobject_name(self, name: Optional[str]) -> None:
        """Set the currently selected mobject by variable name and emit."""
        if self._selected_mobject_name != name:
            self._selected_mobject_name = name
            logger.debug(f"Selection changed: {name}")
            for cb in self._selection_callbacks:
                try:
                    cb(name)
                except Exception as e:
                    logger.error(f"Selection callback failed: {e}")

    def on_selection_changed(self, callback: Callable[[Optional[str]], None]) -> None:
        """Register a callback when an object is clicked/selected."""
        self._selection_callbacks.append(callback)

