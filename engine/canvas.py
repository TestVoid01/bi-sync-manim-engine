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
from typing import TYPE_CHECKING, Any, Optional

import moderngl
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QMouseEvent, QCursor
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

if TYPE_CHECKING:
    from manim.scene.scene import Scene

    from engine.state import EngineState

logger = logging.getLogger("bisync.canvas")


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
                
                # --- PHASE 5 GHOST RENDERER LOGIC ---
                anim_ref = self._engine_state.selected_animation
                ghost_added = False
                ghost_mob = None
                
                if anim_ref is not None and self._ast_mutator is not None:
                    # Dynamic matching using AST bindings
                    binding = self._ast_mutator.get_binding_by_name(anim_ref.target_var)
                    if binding is not None:
                        for mob in self._scene.mobjects:
                            live_bind = self._ast_mutator.get_live_bind(id(mob))
                            if live_bind and live_bind.variable_name == anim_ref.target_var:
                                ghost_mob = mob.copy()
                                break
                        
                        if ghost_mob is None:
                            for mob in self._scene.mobjects:
                                mob_type = type(mob).__name__
                                if mob_type == binding.constructor_name:
                                    ghost_mob = mob.copy()
                                    break
                                    
                        if ghost_mob is not None:
                            # Make it translucent
                            if hasattr(ghost_mob, 'set_fill'):
                                ghost_mob.set_fill(opacity=0.2)
                            if hasattr(ghost_mob, 'set_stroke'):
                                ghost_mob.set_stroke(opacity=0.3, width=2)
                                
                            # Try to apply target state
                            try:
                                method = getattr(ghost_mob, anim_ref.method_name)
                                if len(anim_ref.args) > 0:
                                    method(anim_ref.args[0])
                                else:
                                    method()
                                self._scene.add(ghost_mob)
                                ghost_added = True
                            except Exception as e:
                                logger.debug(f"Ghost apply error: {e}")
                
                self._renderer.update_frame(self._scene)
                
                if ghost_added and ghost_mob is not None:
                    self._scene.remove(ghost_mob)
                    
            except Exception as e:
                logger.error(f"Render error: {e}\n{traceback.format_exc()}")

    def resizeGL(self, width: int, height: int) -> None:
        """Called when the widget is resized.

        Updates the ModernGL viewport and coordinate transformer.
        """
        if self._ctx is not None:
            self._ctx.viewport = (0, 0, width, height)
            logger.debug(f"Viewport resized to {width}x{height}")

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
        if self._drag_controller is not None and self._drag_controller.is_dragging:
            pos = event.position()
            self._drag_controller.on_mouse_move(int(pos.x()), int(pos.y()))
        else:
            # Show open hand cursor when hovering over a hittable object
            if self._drag_controller is not None:
                pos = event.position()
                mx, my = 0.0, 0.0
                if self._coord_transformer:
                    mx, my = self._coord_transformer.pixel_to_math(
                        int(pos.x()), int(pos.y())
                    )
                hit_id = None
                hitboxes = self._engine_state.get_hitboxes()
                for mob_id, (x0, y0, x1, y1) in hitboxes.items():
                    if x0 <= mx <= x1 and y0 <= my <= y1:
                        hit_id = mob_id
                        break
                if hit_id is not None:
                    self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
                else:
                    self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Handle mouse release — finalize drag + AST save."""
        if self._drag_controller is not None and self._drag_controller.is_dragging:
            pos = event.position()
            self._drag_controller.on_mouse_release(int(pos.x()), int(pos.y()))
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        else:
            super().mouseReleaseEvent(event)

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

            # Patch scene.play() to capture animations instead of playing
            original_play = self._scene.play
            original_wait = getattr(self._scene, 'wait', None)
            if self._animation_player is not None:
                player = self._animation_player
                scene_ref = self._scene
                def capturing_play(*animations, **kwargs):
                    """Intercept play() — capture animations, add mobjects."""
                    try:
                        # Compile to proper Animation objects (handles .animate, raw mobjects, etc.)
                        if hasattr(scene_ref, 'compile_animations'):
                            compiled_anims = scene_ref.compile_animations(*animations, **kwargs)
                        else:
                            compiled_anims = animations
                            
                        player.capture_play_call(scene_ref, *compiled_anims, **kwargs)
                    except Exception as e:
                        logger.warning(f"Animation capture error: {e}")
                        compiled_anims = animations
                        
                    # Still add the mobjects so they're visible in static mode
                    for anim in compiled_anims:
                        try:
                            mob = getattr(anim, 'mobject', None)
                            if mob is not None and mob not in scene_ref.mobjects:
                                scene_ref.add(mob)
                        except Exception:
                            pass
                self._scene.play = capturing_play
                self._scene.wait = lambda *a, **kw: None  # skip wait() calls

            try:
                self._scene.construct()
                self._engine_state.scene_is_healthy = True
            except Exception as e:
                self._engine_state.scene_is_healthy = False
                logger.warning(
                    f"Scene.construct() partial failure: {e}\n"
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

    def reload_scene_from_module(self, module_name: str, scene_file: str) -> bool:
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
            
            # Step 0: Clean up old state
            self._engine_state.clear_hitboxes()
            self._engine_state.selected_animation = None
            
            # Step 1: Reload the Python module
            if module_name in sys.modules:
                module = sys.modules[module_name]
                module = importlib.reload(module)
                logger.info(f"Module reloaded: {module_name}")
            else:
                module = importlib.import_module(module_name)
                logger.info(f"Module imported: {module_name}")

            # Step 2: Find the Scene subclass in the reloaded module
            from manim import Scene as BaseScene
            new_scene_class = None
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseScene)
                    and obj is not BaseScene
                ):
                    new_scene_class = obj
                    break

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
                            
                        player.capture_play_call(scene_ref, *compiled_anims, **kwargs)
                    except Exception as e:
                        logger.warning(f"Animation capture error: {e}")
                        compiled_anims = animations
                        
                    for anim in compiled_anims:
                        try:
                            mob = getattr(anim, 'mobject', None)
                            if mob is not None and mob not in scene_ref.mobjects:
                                scene_ref.add(mob)
                        except Exception:
                            pass

                self._scene.play = capturing_play
                self._scene.wait = lambda *a, **kw: None

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
