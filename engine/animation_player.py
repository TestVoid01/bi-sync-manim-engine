"""
Bi-Sync Animation Player — Frame-by-Frame Playback Controller
==============================================================

Drives Manim animations through our hijacked renderer without
blocking the Qt event loop. Works by:

1. CAPTURE: During scene.construct(), intercepts self.play() calls
   and stores animations in a queue instead of executing them.
2. REPLAY: When user presses Play, advances animations frame-by-frame
   using a QTimer (16ms / 60fps), calling animation.interpolate(alpha)
   each tick.
3. CHAIN: Plays animations sequentially — when one finishes, starts next.

Safety:
    - No threading required (single-thread Qt event loop)
    - No OpenGL context issues (renders on main thread)
    - Animations are reversible (Reset restores initial state)
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, List, Optional, Tuple

from PyQt6.QtCore import QTimer

if TYPE_CHECKING:
    from manim import Scene, Animation

logger = logging.getLogger("bisync.animation_player")


class AnimationPlayer:
    """Non-blocking animation playback controller.

    Intercepts scene.play() during construct() to capture animations,
    then replays them frame-by-frame driven by a QTimer.

    States:
        IDLE     → no animations playing
        PLAYING  → advancing current animation each tick
        PAUSED   → frozen at current alpha
    """

    # States
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"

    def __init__(self, engine_state: 'EngineState', fps: int = 60) -> None:
        self._engine_state = engine_state
        self._fps = fps
        self._dt = 1.0 / fps

        # Animation queue: list of (animations_list, run_time, kwargs)
        self._queue: List[Tuple[list, float, dict]] = []
        self._original_queue: List[Tuple[list, float, dict]] = []

        # Current playback state
        self._state = self.IDLE
        self._current_anims: list = []
        self._current_run_time: float = 1.0
        self._current_alpha: float = 0.0
        self._queue_index: int = 0

        # Scene reference
        self._scene: Optional[Scene] = None

        # Playback timer (16ms for 60fps)
        self._timer = QTimer()
        self._timer.setInterval(int(1000 / fps))
        self._timer.timeout.connect(self._tick)

        # Callbacks
        self._on_state_changed = None
        self._on_progress_changed = None

        logger.info(f"AnimationPlayer initialized ({fps}fps)")

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_playing(self) -> bool:
        return self._state == self.PLAYING

    @property
    def progress(self) -> float:
        """Overall progress 0.0 to 1.0 across all animations."""
        total = len(self._original_queue)
        if total == 0:
            return 0.0
        done = self._queue_index
        current_progress = self._current_alpha
        return (done + current_progress) / total

    @property
    def animation_count(self) -> int:
        return len(self._original_queue)

    def set_scene(self, scene) -> None:
        """Set the target scene for animation playback."""
        self._scene = scene

    def set_on_state_changed(self, callback) -> None:
        self._on_state_changed = callback

    def set_on_progress_changed(self, callback) -> None:
        self._on_progress_changed = callback

    # ────────────────────────────────────────────────────────────
    # Capture Phase: Intercept scene.play() during construct()
    # ────────────────────────────────────────────────────────────

    def capture_play_call(self, scene, *animations, **kwargs) -> None:
        """Called instead of scene.play() during construct().

        Stores animations for later replay instead of executing them.
        """
        if not animations:
            return

        run_time = kwargs.get("run_time", None)
        # Get run_time from first animation if not specified
        if run_time is None:
            run_time = getattr(animations[0], "run_time", 1.0)

        anim_list = list(animations)
        entry = (anim_list, run_time, kwargs)
        self._queue.append(entry)
        self._original_queue.append(entry)

        pass




    # ────────────────────────────────────────────────────────────
    # Playback Controls
    # ────────────────────────────────────────────────────────────

    def play(self) -> None:
        """Start or resume playback."""
        if self._state == self.PLAYING:
            return

        if self._state == self.IDLE:
            # Start from beginning
            self._queue_index = 0
            if not self._start_next_animation():
                logger.warning("No animations to play")
                return

        self._state = self.PLAYING
        self._timer.start()
        self._emit_state_changed()
        logger.info("▶ Playback started")

    def pause(self) -> None:
        """Pause playback at current frame."""
        if self._state != self.PLAYING:
            return

        self._state = self.PAUSED
        self._timer.stop()
        self._emit_state_changed()
        logger.info("⏸ Playback paused")

    def stop(self) -> None:
        """Stop playback and reset to beginning."""
        self._timer.stop()
        self._state = self.IDLE
        self._current_alpha = 0.0
        self._queue_index = 0
        self._current_anims = []
        self._emit_state_changed()
        self._emit_progress_changed()
        logger.info("⏹ Playback stopped")

    def reset(self) -> None:
        """Reset to initial state — clears all captured animations.

        Called both by user (Reset button) and by full scene reload.
        After reset, new animations can be captured via capture_play_call.
        """
        self.stop()
        self._queue.clear()
        self._original_queue.clear()
        logger.info("🔄 Animation queue reset (cleared)")

    # ────────────────────────────────────────────────────────────
    # Frame Tick (called by QTimer every 16ms)
    # ────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        """Advance current animation by one frame (dt)."""
        if not self._current_anims or self._scene is None:
            self._timer.stop()
            return

        # Advance alpha
        self._current_alpha += self._dt / self._current_run_time

        if self._current_alpha >= 1.0:
            # Finish current animation
            self._current_alpha = 1.0
            self._interpolate_all(1.0)
            self._finish_current_animations()

            # Move to next animation
            self._queue_index += 1
            if not self._start_next_animation():
                # All animations complete
                self._state = self.IDLE
                self._timer.stop()
                self._emit_state_changed()
                logger.info("✅ All animations complete")
        else:
            # Interpolate current frame
            self._interpolate_all(self._current_alpha)

        self._emit_progress_changed()
        self._engine_state.request_render()

    def _interpolate_all(self, alpha: float) -> None:
        """Apply interpolation to all current animations."""
        for anim in self._current_anims:
            try:
                anim.interpolate(alpha)
            except Exception as e:
                logger.error(f"Animation interpolate error: {e}")

    def _start_next_animation(self) -> bool:
        """Begin the next animation in queue. Returns False if empty."""
        if self._queue_index >= len(self._original_queue):
            return False

        anims, run_time, kwargs = self._original_queue[self._queue_index]
        self._current_run_time = run_time
        self._current_alpha = 0.0
        self._current_anims = []

        for anim in anims:
            try:
                # Set the mobject reference for the animation
                anim._setup_scene(self._scene)
                anim.begin()
                self._current_anims.append(anim)
            except Exception as e:
                logger.error(f"Animation begin() failed: {e}")

        if self._current_anims:
            names = [type(a).__name__ for a in self._current_anims]
            logger.info(
                f"▶ Playing: {names} ({run_time:.1f}s) "
                f"[{self._queue_index + 1}/{len(self._original_queue)}]"
            )
            return True

        return False

    def _finish_current_animations(self) -> None:
        """Finalize current animations."""
        for anim in self._current_anims:
            try:
                anim.finish()
                anim.clean_up_from_scene(self._scene)
            except Exception as e:
                logger.error(f"Animation finish() error: {e}")
        self._current_anims = []

    # ────────────────────────────────────────────────────────────
    # Event Emitters
    # ────────────────────────────────────────────────────────────

    def seek(self, progress: float) -> None:
        """Seek to a specific progress (0.0 to 1.0).
        
        Note: Manim animations aren't perfectly reversible. For a true seek,
        we pause, calculate the target animation index and alpha.
        """
        if not self._original_queue or self._scene is None:
            return

        self.pause()
        
        total = len(self._original_queue)
        target_val = progress * total
        target_index = int(target_val)
        target_alpha = target_val - target_index
        
        if target_index >= total:
            target_index = total - 1
            target_alpha = 1.0

        # We can't perfectly scrub backwards without a full reload, but for
        # draft mode editing, we just jump to the target animation index
        # and interpolate. This might look slightly glitchy but works for UI selection.
        if self._queue_index != target_index or not self._current_anims:
            # Finish current
            self._finish_current_animations()
            
            # Start new target
            self._queue_index = target_index
            self._start_next_animation()
            
        self._current_alpha = target_alpha
        self._interpolate_all(self._current_alpha)
        
        self._emit_progress_changed()
        self._engine_state.request_render()
        
    def _emit_state_changed(self) -> None:
        if self._on_state_changed:
            self._on_state_changed(self._state)

    def _emit_progress_changed(self) -> None:
        if self._on_progress_changed:
            self._on_progress_changed(self.progress)
