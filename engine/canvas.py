"""
Bi-Sync ManimCanvas — The QOpenGLWidget Fusion Core
=====================================================

This is the HEART of Phase 1. A PyQt6 QOpenGLWidget that:
1. Creates an OpenGL context owned by PyQt
2. Hands this context to HijackedRenderer (via standalone=False)
3. Drives the Manim render loop from paintGL()

The "Zero-Copy FBO Hijack":
    Manim's shaders write directly to PyQt's VRAM framebuffer.
    No RAM↔VRAM copy. No IPC. No serialization. Pure GPU.

Critical Implementation Detail:
    ModernGL context is created in paintGL() (first call), NOT in
    initializeGL(). This is because QOpenGLWidget guarantees the GL
    context is "current" during paintGL(), and some Qt backends defer
    full context setup past initializeGL().
"""

from __future__ import annotations

import logging
import traceback
import time
import numpy as np
from typing import TYPE_CHECKING, Any, Optional

import moderngl
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QMouseEvent, QCursor
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from engine.runtime_provenance import reset_creation_tracking
from engine.scene_loader import discover_scene_class

if TYPE_CHECKING:
    from manim.scene.scene import Scene

    from engine.state import EngineState

logger = logging.getLogger("bisync.canvas")

def _args_changed_helper(old_args, new_args):
    """Helper for deep equality check of arguments (handles numpy arrays and floats)."""
    if type(old_args) != type(new_args):
        return True
    if isinstance(old_args, (list, tuple)):
        if len(old_args) != len(new_args):
            return True
        return any(_args_changed_helper(a, b) for a, b in zip(old_args, new_args))
    if hasattr(old_args, 'shape') and hasattr(new_args, 'shape'):
        if old_args.shape != new_args.shape: return True
        return not np.allclose(old_args, new_args, atol=1e-6)
    if isinstance(old_args, float) and isinstance(new_args, float):
        return abs(old_args - new_args) > 1e-6
    return old_args != new_args

class ManimCanvas(QOpenGLWidget):
    """PyQt6 widget that renders Manim scenes via OpenGL Context Hijack.

    Usage:
        canvas = ManimCanvas(DemoScene, engine_state)
        # Add to QMainWindow as central widget
        # Manim scene appears in the widget

    The widget lifecycle:
        1. __init__: Store scene class, engine state
        2. initializeGL: Mark GL as ready (deferred)
        3. paintGL (first call): Create ModernGL ctx, init renderer, construct scene
        4. paintGL (subsequent): Re-detect FBO, render frame
        5. resizeGL: Update viewport

    Safety:
        - All Manim operations are wrapped in try/except
        - GL context creation uses standalone=False (adopts PyQt's context)
        - FBO is re-detected each frame to handle Qt's internal FBO changes
    """

    def __init__(
        self,
        scene_class: type,
        engine_state: EngineState,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)

        self._scene_class = scene_class
        self._engine_state = engine_state

        # Internal state — all set during first paintGL()
        self._ctx: Optional[moderngl.Context] = None
        self._renderer = None  # HijackedRenderer
        self._scene: Optional[Scene] = None
        self._initialized: bool = False
        self._init_error: Optional[str] = None

        # Socket 3: Allow external code to trigger repaints
        self._engine_state.set_render_callback(self._on_render_request)

        # Enable mouse tracking for future Phase 3
        self.setMouseTracking(True)

        # Request focus for keyboard events
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Frame counter for diagnostics
        self._frame_count: int = 0

        # Hover hit-test throttle: skip if cursor barely moved
        self._last_hover_px: int = -999
        self._last_hover_py: int = -999
        self._last_hover_hit: bool = False

        # Drag controller (set externally by MainWindow)
        self._drag_controller = None
        # Coordinate transformer (set externally by MainWindow)
        self._coord_transformer = None
        # Animation player (set externally by MainWindow)
        self._animation_player = None
        # AST Mutator (set externally by MainWindow for binding lookups)
        self._ast_mutator = None

        # 60fps render timer — drives continuous paintGL() calls
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self.update)

        logger.info(f"ManimCanvas created for scene: {scene_class.__name__}")

    def _on_render_request(self, dt: float = 0.0) -> None:
        """Socket 3 callback: Trigger a repaint from external code.

        Phase 2 will call engine_state.request_render() after code
        hot-swap, which routes here to trigger paintGL().
        """
        self.update()  # Schedules a paintGL() call

    # ────────────────────────────────────────────────────────────
    # QOpenGLWidget Lifecycle
    # ────────────────────────────────────────────────────────────

    def initializeGL(self) -> None:
        """Called once when the widget's OpenGL context is first made current.

        We do NOT create the ModernGL context here. Deferred to paintGL()
        because some Qt backends don't fully set up the GL context
        until the first paint event.
        """
        logger.info("initializeGL called — deferring actual init to paintGL")

    def paintGL(self) -> None:
        """Called every time the widget needs repainting.

        First call: Full initialization (context, renderer, scene).
        Subsequent calls: Re-detect FBO and render frame.
        """
        # First-time initialization
        if not self._initialized:
            self._do_first_init()
            self._initialized = True

        # If init failed, don't try to render
        if self._init_error is not None:
            return

        # Render the current Manim scene
        if self._scene is not None and self._renderer is not None:
            try:
                # Re-detect FBO each frame to handle Qt's internal
                # FBO recreation on resize. This is a cheap GL query.
                self._renderer.update_fbo()
                
                anim_ref = self._engine_state.selected_animation
                
                if anim_ref is None:
                    # Clean up ghost if animation is deselected
                    if getattr(self, '_cached_ghost_mob', None) is not None:
                        if self._scene is not None:
                            try:
                                self._scene.remove(self._cached_ghost_mob)
                            except Exception:
                                pass
                        self._cached_ghost_mob = None
                        self._cached_base_ghost = None
                        self._cached_anim_key = None
                        self._cached_anim_args = None
                        self._cached_anim_method = None
                else:
                    # Ghost rendering is disabled to prevent "duplicate object" visual confusion.
                    pass
                
                # Run all mobject updaters (always_redraw, etc.) every frame
                # This keeps animations like orbit vectors, moving text, etc. alive
                if self._scene is not None:
                    try:
                        current_time = time.monotonic()
                        last_time = getattr(self, '_last_frame_time', current_time - 1.0/60.0)
                        dt = current_time - last_time
                        
                        # Clamp dt to prevent massive jumps if the window is hidden/paused
                        if dt > 0.1:
                            dt = 1.0 / 60.0
                            
                        self._last_frame_time = current_time
                        self._scene.update_mobjects(dt)
                    except Exception as e:
                        logger.debug(f"update_mobjects skipped: {e}")

                self._renderer.update_frame(self._scene)
                    
            except Exception as e:
                logger.error(f"Render error: {e}\n{traceback.format_exc()}")

    def resizeGL(self, width: int, height: int) -> None:
        """Called when the widget is resized.

        Updates the ModernGL viewport and coordinate transformer.
        """
        if self._ctx is not None:
            self._ctx.viewport = (0, 0, width, height)
            pass

        # Update coordinate transformer with new widget dimensions
        if self._coord_transformer is not None:
            self._coord_transformer.set_widget_size(width, height)

    # ────────────────────────────────────────────────────────────
    # Mouse Events (Phase 4: Interactive Canvas)
    # ────────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press — hit-test and start drag."""
        if self._drag_controller is None or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        pos = event.position()
        if self._drag_controller.on_mouse_press(int(pos.x()), int(pos.y())):
            # Object selected — change cursor to closed hand
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle mouse move — update drag position (SPSC overwrite)."""
        if (
            self._drag_controller is not None
            and (
                self._drag_controller.is_dragging
                or self._drag_controller.has_pending_drag_candidate
            )
        ):
            pos = event.position()
            self._drag_controller.on_mouse_move(int(pos.x()), int(pos.y()))
        else:
            # Throttled hover cursor: only re-test if mouse moved ≥5px
            if self._drag_controller is not None:
                pos = event.position()
                px, py = int(pos.x()), int(pos.y())
                dx = abs(px - self._last_hover_px)
                dy = abs(py - self._last_hover_py)
                if dx >= 5 or dy >= 5:
                    self._last_hover_px = px
                    self._last_hover_py = py
                    mx, my = 0.0, 0.0
                    if self._coord_transformer:
                        mx, my = self._coord_transformer.pixel_to_math(px, py)
                    hit_found = False
                    hitboxes = self._engine_state.get_hitboxes()
                    for mob_id, (x0, y0, x1, y1) in hitboxes.items():
                        if x0 <= mx <= x1 and y0 <= my <= y1:
                            hit_found = True
                            break
                    if hit_found != self._last_hover_hit:
                        self._last_hover_hit = hit_found
                        if hit_found:
                            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
                        else:
                            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Handle mouse release — finalize drag + AST save."""
        if (
            self._drag_controller is not None
            and (
                self._drag_controller.is_dragging
                or self._drag_controller.has_pending_drag_candidate
            )
        ):
            self._drag_controller.on_mouse_release()
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Handle mouse double click to toggle isolation mode."""
        if self._drag_controller is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return

        pos = event.position()
        if self._drag_controller.on_mouse_double_click(int(pos.x()), int(pos.y())):
            pass
        else:
            super().mouseDoubleClickEvent(event)

    # ────────────────────────────────────────────────────────────
    # First-Time Initialization (runs once in first paintGL)
    # ────────────────────────────────────────────────────────────

    def _do_first_init(self) -> None:
        """Perform the full OpenGL Context Hijack initialization.

        This runs exactly ONCE during the first paintGL() call.
        At this point, Qt guarantees the GL context is current.

        Flow:
            1. Create ModernGL context (standalone=False → adopts PyQt's)
            2. Create HijackedRenderer and inject context
            3. Create Manim Scene with our renderer
            4. Init renderer with scene (sets up FBO, blending)
            5. Run scene.construct() to populate mobjects
            6. Emit scene_parsed event for Phase 2 hooks
        """
        logger.info("═══ FIRST INIT: OpenGL Context Hijack Starting ═══")

        try:
            # ── Step 1: Create ModernGL context ──
            # standalone=False is CRITICAL — it adopts the existing GL
            # context that PyQt has already created and made current.
            # Without standalone=False, ModernGL would create a NEW
            # invisible context, defeating the entire hijack.
            self._ctx = moderngl.create_context(standalone=False, require=330)
            logger.info(
                f"ModernGL context created (standalone=False): "
                f"GL {self._ctx.version_code}, "
                f"Vendor: {self._ctx.info.get('GL_VENDOR', 'unknown')}"
            )

            # ── Step 2: Create and configure HijackedRenderer ──
            from engine.renderer import HijackedRenderer

            self._renderer = HijackedRenderer(engine_state=self._engine_state)
            self._renderer.set_external_context(self._ctx)

            # ── Step 3: Create Manim Scene with our renderer ──
            self._scene = self._scene_class(renderer=self._renderer)
            logger.info(f"Scene created: {self._scene_class.__name__}")

            # ── Step 4: Initialize renderer with scene ──
            # This sets up FBO (via detect_framebuffer), blending, etc.
            self._renderer.init_scene(self._scene)

            # ── Step 5: Build the scene (populate mobjects) ──
            # setup() does pre-construct initialization
            # construct() is where user adds Circle, Square, etc.
            try:
                self._scene.setup()
            except Exception as e:
                logger.warning(f"Scene.setup() issue (non-fatal): {e}")
            reset_creation_tracking()

            # Patch scene.play() to capture animations instead of playing
            original_play = self._scene.play
            original_wait = getattr(self._scene, 'wait', None)
            if self._animation_player is not None:
                player = self._animation_player
                scene_ref = self._scene
                
                def capturing_play(*animations, **kwargs):
                    """Intercept play() — capture animations, add mobjects."""
                    try:
                        # Compile to proper Animation objects
                        if hasattr(scene_ref, 'compile_animations'):
                            compiled_anims = scene_ref.compile_animations(*animations, **kwargs)
                        else:
                            compiled_anims = animations

                        # 1. Add introducers / mobjects to the scene so they are visible
                        for anim in compiled_anims:
                            try:
                                if hasattr(anim, "is_introducer") and anim.is_introducer():
                                    mob = getattr(anim, 'mobject', None)
                                    if mob is not None and mob not in scene_ref.mobjects:
                                        scene_ref.add(mob)
                                elif hasattr(anim, "add_to_back") and anim not in scene_ref.mobjects:
                                    scene_ref.add(anim)
                                else:
                                    mob = getattr(anim, 'mobject', None)
                                    if mob is not None and mob not in scene_ref.mobjects:
                                        scene_ref.add(mob)
                            except Exception as e:
                                logger.error(f"Animation introducer error: {e}", exc_info=True)

                        # 2. VBO pre-allocation
                        try:
                            self._renderer.update_frame(scene_ref)
                        except Exception as e:
                            logger.error(f"VBO pre-allocation error: {e}", exc_info=True)

                        # 3. Snapshot BEFORE begin()
                        state_snapshot = {id(m): m.copy() for m in scene_ref.mobjects}

                        # 4. Initialize animations
                        for anim in compiled_anims:
                            anim.begin()

                        # 5. Capture
                        player.capture_play_call(scene_ref, compiled_anims, kwargs, state_snapshot)

                        # 6. FAST-FORWARD: advance mobjects to their final state
                        # so that subsequent code in construct() operates on completed mobjects.
                        for anim in compiled_anims:
                            try:
                                anim.interpolate(1)
                                anim.finish()
                                anim.clean_up_from_scene(scene_ref)
                            except Exception as e:
                                logger.warning(f"Fast-forward error: {e}")
                    except Exception as e:
                        logger.warning(f"Animation capture error: {e}")

                def capturing_wait(duration=1, **kwargs):
                    """Intercept wait() — capture as a Wait animation."""
                    try:
                        from manim import Wait
                        w = Wait(duration=duration, **kwargs)
                        state_snapshot = {id(m): m.copy() for m in scene_ref.mobjects}
                        w.begin()
                        player.capture_play_call(scene_ref, [w], kwargs, state_snapshot)
                    except Exception as e:
                        logger.warning(f"Wait capture error: {e}")

                self._scene.play = capturing_play
                self._scene.wait = capturing_wait

            try:
                self._scene.construct()
                self._engine_state.scene_is_healthy = True
            except Exception as e:
                self._engine_state.scene_is_healthy = False
                logger.error(
                    f"Scene.construct() failure: {e}\n"
                    f"{traceback.format_exc()}"
                )
                logger.warning(
                    f"Showing {len(self._scene.mobjects)} objects added before error"
                )

            # Restore original play
            self._scene.play = original_play
            if original_wait is not None:
                self._scene.wait = original_wait

            anim_count = self._animation_player.animation_count if self._animation_player else 0
            logger.info(
                f"Scene constructed: {len(self._scene.mobjects)} mobjects, "
                f"{anim_count} animations captured"
            )

            # ── Step 6: Fire Phase 2 hook ──
            self._engine_state.emit_scene_parsed()

            # ── Step 7: Start 60fps render timer ──
            self._render_timer.start(16)  # ~60fps (1000ms / 60 ≈ 16ms)
            logger.info("60fps render timer started (16ms interval)")

            logger.info("═══ FIRST INIT COMPLETE: Context Hijack Successful ═══")

        except Exception as e:
            self._init_error = str(e)
            logger.critical(
                f"═══ FIRST INIT FAILED ═══\n"
                f"Error: {e}\n"
                f"{traceback.format_exc()}"
            )

    # ────────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────────

    def set_drag_controller(self, controller) -> None:
        """Set the drag controller for mouse interaction."""
        self._drag_controller = controller

    def set_coord_transformer(self, transformer) -> None:
        """Set the coordinate transformer for pixel→math conversion."""
        self._coord_transformer = transformer

    def set_animation_player(self, player: Any) -> None:
        """Wire the animation player to this canvas."""
        self._animation_player = player
        
    def set_ast_mutator(self, mutator: Any) -> None:
        """Wire the AST Mutator to this canvas for binding lookups."""
        self._ast_mutator = mutator

    def get_scene(self) -> Optional[Scene]:
        """Return the current Manim scene (or None if not initialized)."""
        return self._scene

    def get_renderer(self):
        """Return the HijackedRenderer (or None if not initialized)."""
        return self._renderer

    def get_context(self) -> Optional[moderngl.Context]:
        """Return the ModernGL context (or None if not initialized)."""
        return self._ctx

    def request_render_validation(
        self,
        priming_frames: int = 1,
        health_checks: int = 1,
    ) -> None:
        """Compatibility hook for MainWindow post-reload validation.

        Older MainWindow flows call this after scene wiring to "prime" a few
        frames. In this build we can safely schedule those repaints directly.
        """
        del health_checks
        frame_count = max(1, int(priming_frames))
        for _ in range(frame_count):
            self.update()

    def shadow_validate_scene_source(
        self,
        source_text: str,
        module_name: str,
        scene_file: str,
        preferred_scene_name: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Validate candidate scene code without mutating live preview."""
        try:
            import ast as ast_mod

            ast_mod.parse(source_text)

            compiled = compile(source_text, scene_file, "exec")
            ns: dict[str, Any] = {"__name__": module_name}
            exec("from manim import *", ns)
            exec(compiled, ns)

            scene_class = discover_scene_class(
                ns,
                preferred_name=preferred_scene_name,
            )
            if scene_class is None:
                return False, f"no Scene subclass found in {module_name}"

            return True, "shadow validation passed"
        except Exception as exc:
            return False, str(exc)

    def reload_scene_from_module(
        self,
        module_name: str,
        scene_file: str,
        preferred_scene_name: Optional[str] = None,
    ) -> bool:
        """Full scene reload — destroys old scene, creates fresh one.

        Called when file structure changes (new objects, deleted objects).
        Preserves OpenGL context and renderer — only Python scene is rebuilt.

        Flow:
            1. importlib.reload() the scene module for fresh class
            2. Create new scene with SAME renderer (no GL recreation)
            3. Re-init renderer with new scene (FBO preserved)
            4. Patch play() to capture animations
            5. Call construct()
            6. Emit scene_parsed for MainWindow re-wiring

        Args:
            module_name: Python module path (e.g., "scenes.advanced_scene")
            scene_file: Absolute path to the .py file

        Returns:
            True if reload succeeded
        """
        if self._renderer is None or self._ctx is None:
            logger.warning("Cannot reload scene: renderer not initialized")
            return False

        import importlib
        import sys

        logger.info("═══ FULL SCENE RELOAD Starting ═══")

        try:
            # We MUST ensure the context is active during reload,
            # otherwise Manim's init_scene will lose track of the FBO.
            self.makeCurrent()
            
            # Step 0: Clean up old state comprehensively
            self._engine_state.clear_hitboxes()
            self._engine_state.selected_animation = None
            self._engine_state.set_selected_object(None)
            self._engine_state.clear_preview_drift()

            # Clear object registry to prevent ghost references
            if hasattr(self._engine_state, 'object_registry'):
                self._engine_state.object_registry.clear()

            # Clear AST live_binds so stale mobject_id mappings don't persist
            if hasattr(self, '_ast_mutator') and self._ast_mutator is not None:
                clear_fn = getattr(self._ast_mutator, 'clear_live_binds', None)
                if callable(clear_fn):
                    clear_fn()
                elif hasattr(self._ast_mutator, '_live_binds'):
                    self._ast_mutator._live_binds.clear()
            
            # Step 1: Reload the Python module
            if module_name in sys.modules:
                module = sys.modules[module_name]
                module = importlib.reload(module)
                logger.info(f"Module reloaded: {module_name}")
            else:
                module = importlib.import_module(module_name)
                logger.info(f"Module imported: {module_name}")

            # Step 2: Find the Scene subclass in the reloaded module
            new_scene_class = discover_scene_class(
                module,
                preferred_name=preferred_scene_name,
            )
            if new_scene_class is None:
                logger.error("No Scene subclass found in reloaded module")
                return False

            logger.info(f"Found scene class: {new_scene_class.__name__}")

            # Step 3: Clear old scene
            if self._scene is not None:
                self._scene.mobjects.clear()

            # Step 4: Create new scene with SAME renderer
            self._scene_class = new_scene_class
            self._scene = new_scene_class(renderer=self._renderer)

            # Step 5: Re-init renderer with new scene
            # Critical Fix: Refresh FBO right before init_scene
            self._renderer.update_fbo()
            self._renderer.init_scene(self._scene)

            # Step 6: Setup
            try:
                self._scene.setup()
            except Exception as e:
                logger.warning(f"Scene.setup() issue (non-fatal): {e}")
            reset_creation_tracking()

            # Step 7: Patch play() for animation capture
            original_play = self._scene.play
            original_wait = getattr(self._scene, 'wait', None)
            if self._animation_player is not None:
                self._animation_player.reset()
                player = self._animation_player
                scene_ref = self._scene

                def capturing_play(*animations, **kwargs):
                    try:
                        # Compile to proper Animation objects (handles .animate, raw mobjects, etc.)
                        if hasattr(scene_ref, 'compile_animations'):
                            compiled_anims = scene_ref.compile_animations(*animations, **kwargs)
                        else:
                            compiled_anims = animations
                            
                        # 1. Add introducers / mobjects to the scene so they are visible
                        for anim in compiled_anims:
                            try:
                                if hasattr(anim, "is_introducer") and anim.is_introducer():
                                    mob = getattr(anim, 'mobject', None)
                                    if mob is not None and mob not in scene_ref.mobjects:
                                        scene_ref.add(mob)
                                elif hasattr(anim, "add_to_back") and anim not in scene_ref.mobjects:
                                    scene_ref.add(anim)
                                else:
                                    mob = getattr(anim, 'mobject', None)
                                    if mob is not None and mob not in scene_ref.mobjects:
                                        scene_ref.add(mob)
                            except Exception as e:
                                logger.error(f"Animation introducer error (reload): {e}", exc_info=True)

                        # 2. RUN DUMMY VBO PRE-ALLOCATION BEFORE BEGIN()
                        try:
                            self._renderer.update_frame(scene_ref)
                        except Exception as e:
                            logger.error(f"VBO pre-allocation error (reload): {e}", exc_info=True)

                        # 3. Take snapshot exactly BEFORE begin()
                        state_snapshot = {id(m): m.copy() for m in scene_ref.mobjects}

                        # 4. Initialize animations
                        for anim in compiled_anims:
                            anim.begin()
                            
                        # 5. Capture play call properly
                        player.capture_play_call(scene_ref, compiled_anims, kwargs, state_snapshot)

                        # 6. FAST-FORWARD: advance mobjects to their final state
                        for anim in compiled_anims:
                            try:
                                anim.interpolate(1)
                                anim.finish()
                                anim.clean_up_from_scene(scene_ref)
                            except Exception as e:
                                logger.warning(f"Fast-forward error in reload: {e}")
                    except Exception as e:
                        logger.warning(f"Animation capture error: {e}")

                def capturing_wait(duration=1, **kwargs):
                    try:
                        from manim import Wait
                        w = Wait(duration=duration, **kwargs)
                        state_snapshot = {id(m): m.copy() for m in scene_ref.mobjects}
                        w.begin()
                        player.capture_play_call(scene_ref, [w], kwargs, state_snapshot)
                    except Exception as e:
                        logger.warning(f"Wait capture error: {e}")

                self._scene.play = capturing_play
                self._scene.wait = capturing_wait

            # Step 8: Construct (wrapped — partial scenes are OK)
            try:
                self._scene.construct()
                self._engine_state.scene_is_healthy = True
            except Exception as e:
                self._engine_state.scene_is_healthy = False
                logger.warning(
                    f"construct() partial failure: {e}\n"
                    f"Showing {len(self._scene.mobjects)} objects added before error"
                )

            # Restore original play/wait
            self._scene.play = original_play
            if original_wait is not None:
                self._scene.wait = original_wait

            anim_count = (
                self._animation_player.animation_count
                if self._animation_player else 0
            )
            logger.info(
                f"Scene reconstructed: {len(self._scene.mobjects)} mobjects, "
                f"{anim_count} animations captured"
            )

            # Step 9: Emit for MainWindow re-wiring
            if hasattr(self, '_last_frame_time'):
                delattr(self, '_last_frame_time')
            self._engine_state.emit_scene_parsed()

            # Step 10: Force repaint
            self.update()

            logger.info("═══ FULL SCENE RELOAD COMPLETE ═══")
            return True

        except Exception as e:
            logger.error(
                f"═══ FULL SCENE RELOAD FAILED ═══\n"
                f"Error: {e}\n{traceback.format_exc()}"
            )
            return False
