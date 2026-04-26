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

from engine.object_registry import ObjectRegistry

if TYPE_CHECKING:
    from engine.ast_mutator import ASTAnimationRef
    from engine.object_registry import SelectionRef

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

    # Render lifecycle states used by MainWindow transition flow.
    RENDER_READY = "ready"
    RENDER_LOADING = "loading"
    RENDER_UNHEALTHY = "unhealthy"

    # Session State Machine
    STATE_IDLE = "idle"
    STATE_PREVIEWING = "previewing"
    STATE_COMMIT_PENDING = "commit_pending"
    STATE_COMMITTING = "committing"
    STATE_SETTLED = "settled"

    # Reload Governor Policies
    RELOAD_ALLOW_FULL = "allow_full"
    RELOAD_PREFER_PROPERTY_ONLY = "prefer_property_only"
    RELOAD_BLOCK_DURING_BURST = "block_during_burst"

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
        self.render_state: str = self.RENDER_READY
        self.interaction_burst_active: bool = False
        self.interaction_session_state: str = self.STATE_IDLE
        self.reload_guard_mode: str = self.RELOAD_ALLOW_FULL
        self._interaction_state_callbacks: list[Callable[[str], None]] = []

        # ── Phase 5: Selected Animation for Visual Editing ──
        self.selected_animation: Optional[ASTAnimationRef] = None

        # ── Phase 6: Deep Graphical Control (Selection Tracking) ──
        self.object_registry = ObjectRegistry()
        self._selected_object: Optional["SelectionRef"] = None
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
        pass

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
        pass

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
        pass

    def resume_file_watcher(self) -> None:
        """Resume QFileSystemWatcher after drag/slider release."""
        self._file_watcher_paused = False
        pass

    @property
    def is_file_watcher_paused(self) -> bool:
        """Check if file watcher is currently paused."""
        return self._file_watcher_paused

    def set_file_watcher(self, watcher: Any) -> None:
        """Register the file watcher instance for Socket 5 control."""
        self._file_watcher = watcher
        pass

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

    def on_interaction_state_changed(self, callback: Callable[[str], None]) -> None:
        self._interaction_state_callbacks.append(callback)

    def set_interaction_state(self, state: str) -> None:
        if self.interaction_session_state == state:
            return
        self.interaction_session_state = state
        for cb in self._interaction_state_callbacks:
            try:
                cb(state)
            except Exception as e:
                logger.error(f"Interaction state callback failed: {e}")

    # ────────────────────────────────────────────────────────────
    # Scene transition state
    # ────────────────────────────────────────────────────────────

    def mark_scene_transition(self, render_state: Optional[str] = None) -> None:
        """Mark scene as transitioning/reloading."""
        self.scene_is_healthy = False
        self.render_state = render_state or self.RENDER_LOADING

    def mark_scene_unhealthy(self) -> None:
        """Mark scene as unhealthy after reload/render failure."""
        self.scene_is_healthy = False
        self.render_state = self.RENDER_UNHEALTHY

    def mark_scene_ready(self) -> None:
        """Mark scene as healthy and fully ready."""
        self.scene_is_healthy = True
        self.render_state = self.RENDER_READY

    # ────────────────────────────────────────────────────────────
    # Phase 6: Selection State Control
    # ────────────────────────────────────────────────────────────

    @property
    def selected_object(self) -> Optional["SelectionRef"]:
        return self._selected_object

    def set_selected_object(self, selection: Optional["SelectionRef"]) -> None:
        """Set canonical object selection payload and emit legacy name signal."""
        self._selected_object = selection
        name = selection.display_name if selection is not None else None
        self.set_selected_mobject_name(name)

    @property
    def selected_mobject_name(self) -> Optional[str]:
        return self._selected_mobject_name

    def set_selected_mobject_name(self, name: Optional[str]) -> None:
        """Set the currently selected mobject by variable name and emit."""
        if self._selected_mobject_name != name:
            self._selected_mobject_name = name
            pass
            for cb in self._selection_callbacks:
                try:
                    cb(name)
                except Exception as e:
                    logger.error(f"Selection callback failed: {e}")

    def on_selection_changed(self, callback: Callable[[Optional[str]], None]) -> None:
        """Register a callback when an object is clicked/selected."""
        self._selection_callbacks.append(callback)

