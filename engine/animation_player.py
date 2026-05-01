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

        # Animation queue: list of (animations_list, run_time, kwargs, state_snapshot)
        self._queue: List[Tuple[list, float, dict, dict]] = []
        self._original_queue: List[Tuple[list, float, dict, dict]] = []
        
        # Keep track of ALL real mobjects ever introduced to avoid using clones
        self._all_mobs: Dict[int, Any] = {}

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

    def capture_play_call(self, scene, anim_list, kwargs, state_snapshot) -> None:
        """Called instead of scene.play() during construct().

        Stores animations for later replay instead of executing them.
        """
        if not anim_list:
            return

        run_time = kwargs.get("run_time", None)
        # Get max run_time from all animations if not specified
        if run_time is None:
            run_time = max((getattr(a, "run_time", 1.0) for a in anim_list), default=1.0)

        entry = (anim_list, run_time, kwargs, state_snapshot)
        self._queue.append(entry)
        self._original_queue.append(entry)

        # Save real mobject references
        for mob in scene.mobjects:
            if id(mob) not in self._all_mobs:
                self._all_mobs[id(mob)] = mob




    # ────────────────────────────────────────────────────────────
    # Playback Controls
    # ────────────────────────────────────────────────────────────

    def update_snapshot(self, original_mob: Any, updater_func: Any) -> None:
        """Applies an updater function to all snapshot copies of the given mobject."""
        mob_key = id(original_mob)
        for entry in self._original_queue:
            state_snapshot = entry[3]
            if mob_key in state_snapshot:
                copied_state = state_snapshot[mob_key]
                try:
                    updater_func(copied_state)
                except Exception as e:
                    logger.warning(f"Failed to update snapshot: {e}")

    def play(self) -> None:
        """Start or resume playback."""
        if self._state == self.PLAYING:
            return

        if self._state == self.IDLE:
            # Start from beginning
            self._queue_index = 0
            if not self._start_next_animation(is_seek=True):
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
        self._all_mobs.clear()
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
            self._scene.update_mobjects(self._dt)
            self._interpolate_all(1.0)
            self._finish_current_animations()

            # Move to next animation
            self._queue_index += 1
            if not self._start_next_animation(is_seek=False):
                # All animations complete
                self._state = self.IDLE
                self._timer.stop()
                self._emit_state_changed()
                logger.info("✅ All animations complete")
        else:
            # Interpolate current frame
            self._scene.update_mobjects(self._dt)
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

    def _start_next_animation(self, is_seek: bool = False) -> bool:
        """Begin the next animation in queue. Returns False if empty."""
        if self._queue_index >= len(self._original_queue):
            return False

        anims, run_time, kwargs, state_snapshot = self._original_queue[self._queue_index]
        self._current_run_time = run_time
        self._current_alpha = 0.0
        self._current_anims = []

        # Delta-based state tracking:
        # Only fully restore the snapshot using heavy become() calls when seeking!
        # During normal playback, the objects are already in the correct state.
        live_mobs = {id(m): m for m in self._scene.mobjects}
        engine_mobs = [m for m in self._scene.mobjects if getattr(m, '_is_engine_mobject', False)]

        if is_seek:
            self._scene.mobjects.clear()
            for mob_key, copied_state in state_snapshot.items():
                # ALWAYS use the real mobject if we know it!
                original_mob = self._all_mobs.get(mob_key, live_mobs.get(mob_key))
                
                if original_mob is not None:
                    # In-place restore to preserve object identity!
                    # become() destroys submobject references, breaking Animation targets.
                    try:
                        t_fam = original_mob.get_family() if hasattr(original_mob, 'get_family') else [original_mob]
                        s_fam = copied_state.get_family() if hasattr(copied_state, 'get_family') else [copied_state]
                        if len(t_fam) != len(s_fam):
                            original_mob.become(copied_state)
                        else:
                            import numpy as np
                            for t, s in zip(t_fam, s_fam):
                                if hasattr(t, 'points') and hasattr(s, 'points'):
                                    t.points = np.copy(s.points)
                                if hasattr(t, 'interpolate_color'):
                                    try:
                                        t.interpolate_color(t, s, 1.0)
                                    except Exception:
                                        pass
                                if hasattr(t, 'data') and hasattr(s, 'data'):
                                    for key in s.data:
                                        if key in t.data:
                                            try:
                                                t.data[key] = np.copy(s.data[key])
                                            except Exception:
                                                pass
                    except Exception as e:
                        logger.warning(f"In-place restore failed: {e}")
                        original_mob.become(copied_state)

                    # FORCE OPENGL VBO AND STYLING REFRESH:
                    for sub_mob in original_mob.get_family():
                        if hasattr(sub_mob, 'needs_new_bounding_box'):
                            sub_mob.needs_new_bounding_box = True
                        try:
                            if hasattr(sub_mob, 'data') and 'rgbas' in sub_mob.data:
                                if len(sub_mob.rgbas) == 0:
                                    sub_mob.set_color("#FFFFFF")
                        except Exception:
                            pass

                    self._scene.mobjects.append(original_mob)
                else:
                    self._scene.mobjects.append(copied_state)
            
            # Re-add engine mobjects that were not in the snapshot
            for emob in engine_mobs:
                if emob not in self._scene.mobjects:
                    self._scene.mobjects.append(emob)
        else:
            # Sequential playback: avoid heavy become() calls.
            # Just ensure newly created objects stay, and objects from snapshot are ordered.
            new_mobjects = []
            for mob_key in state_snapshot.keys():
                original_mob = self._all_mobs.get(mob_key, live_mobs.get(mob_key))
                if original_mob is not None:
                    new_mobjects.append(original_mob)
                else:
                    new_mobjects.append(state_snapshot[mob_key])
            
            # Preserve user objects created dynamically and engine objects
            for mob in self._scene.mobjects:
                if id(mob) not in state_snapshot and mob not in new_mobjects:
                    new_mobjects.append(mob)

            self._scene.mobjects = new_mobjects
        for anim in anims:
            try:
                # Set the mobject reference for the animation
                anim._setup_scene(self._scene)
                
                # We do NOT call anim.begin() here to avoid duplicate initialization crashes!
                # Instead, we directly enforce the starting visual state by interpolating to 0.0.
                # This prevents "flash" bugs where an object (like Create) appears fully drawn 
                # before the first frame of animation.
                if hasattr(anim, 'interpolate'):
                    anim.interpolate(0.0)
                
                self._current_anims.append(anim)
            except Exception as e:
                logger.error(f"Animation setup failed: {e}")

        # CRITICAL FIX FOR INVISIBLE MOBJECTS (like chaos_path):
        if hasattr(self._scene, 'renderer') and hasattr(self._scene.renderer, 'update_frame'):
            try:
                self._scene.renderer.update_frame(self._scene)
            except Exception as e:
                logger.warning(f"VBO pre-allocation frame failed: {e}")

        # Prevent 1-frame flash of full mobjects by interpolating at alpha=0.0 immediately
        if self._current_anims:
            self._interpolate_all(0.0)
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

    def _restore_base_state_for_active_anims(self) -> None:
        """Deep state delta-tracking: Only restores the base state for objects 
        actively participating in the current animation to avoid heavy become() calls.
        This prevents ghosting from non-reversible animations when scrubbing backwards.
        """
        if not self._current_anims or self._queue_index >= len(self._original_queue):
            return
            
        state_snapshot = self._original_queue[self._queue_index][3]
        
        # Identify actively animated mobjects
        animating_mobs = set()
        for anim in self._current_anims:
            mob = getattr(anim, 'mobject', None)
            if mob is not None:
                animating_mobs.add(mob)
                if hasattr(mob, 'get_family'):
                    animating_mobs.update(mob.get_family())

        # Delta-restore: Apply in-place restore to preserve object identity bindings
        for mob in animating_mobs:
            mob_key = id(mob)
            if mob_key in state_snapshot:
                copied_state = state_snapshot[mob_key]
                
                try:
                    t_fam = mob.get_family() if hasattr(mob, 'get_family') else [mob]
                    s_fam = copied_state.get_family() if hasattr(copied_state, 'get_family') else [copied_state]
                    if len(t_fam) != len(s_fam):
                        mob.become(copied_state)
                    else:
                        import numpy as np
                        for t, s in zip(t_fam, s_fam):
                            if hasattr(t, 'points') and hasattr(s, 'points'):
                                t.points = np.copy(s.points)
                            if hasattr(t, 'interpolate_color'):
                                try:
                                    t.interpolate_color(t, s, 1.0)
                                except Exception:
                                    pass
                            if hasattr(t, 'data') and hasattr(s, 'data'):
                                for key in s.data:
                                    if key in t.data:
                                        try:
                                            t.data[key] = np.copy(s.data[key])
                                        except Exception:
                                            pass
                except Exception as e:
                    logger.warning(f"In-place active restore failed: {e}")
                    mob.become(copied_state)

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
            # We are jumping. Do not call finish() which might pollute state.
            # Just clear current anims.
            for anim in self._current_anims:
                try:
                    anim.clean_up_from_scene(self._scene)
                except Exception:
                    pass
            self._current_anims = []
            
            # Start new target
            self._queue_index = target_index
            self._start_next_animation(is_seek=True)
        else:
            # Delta-based state tracking system:
            # We are scrubbing within the SAME animation.
            # To ensure forward-only interpolation and avoid ghosting from
            # non-reversible animations, we restore the base state first!
            self._restore_base_state_for_active_anims()
            
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
