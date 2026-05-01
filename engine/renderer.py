"""
Bi-Sync HijackedRenderer — OpenGL Context Hijack
==================================================

Subclasses Manim's OpenGLRenderer to accept an EXTERNAL
ModernGL context (from PyQt6's QOpenGLWidget) instead of
creating its own window or standalone context.

The Hijack Flow:
    1. PyQt6 creates QOpenGLWidget → OS allocates GPU context
    2. ManimCanvas creates ModernGL ctx (standalone=False) → adopts PyQt's context
    3. HijackedRenderer receives this ctx via set_external_context()
    4. init_scene() uses ctx.detect_framebuffer() → gets PyQt's FBO
    5. All Manim draw calls now go into PyQt's VRAM

Safety:
    - should_create_window() always returns False (no rogue Manim windows)
    - NullFileWriter prevents any SSD I/O during rendering
    - All inherited render methods (render_mobject, update_frame) work unmodified
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

import moderngl
import numpy as np

from manim import config
from manim.renderer.opengl_renderer import OpenGLRenderer
from manim.mobject.opengl.opengl_mobject import OpenGLMobject
from manim.mobject.opengl.opengl_vectorized_mobject import OpenGLVMobject

# Maximum depth for recursive hitbox extraction to avoid traversing
# thousands of leaf nodes in complex scenes (e.g., NumberPlane).
_HITBOX_MAX_DEPTH = 4

if TYPE_CHECKING:
    from manim.scene.scene import Scene
    from engine.state import EngineState

logger = logging.getLogger("bisync.renderer")


class NullFileWriter:
    """No-op file writer that prevents all SSD I/O.

    Manim's OpenGLRenderer.init_scene() creates a SceneFileWriter
    which tries to create output directories. We don't want that—
    our engine renders to screen, not to files.

    Safety: Every method is a safe no-op. No filesystem side effects.
    """

    def __init__(self, renderer: Any, scene_name: str) -> None:
        # Manim's update_skipping_status() accesses self.file_writer.sections[-1]
        # We provide a minimal stub to prevent AttributeError
        self.sections = [_NullSection()]

    def begin_animation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def end_animation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def write_frame(self, *args: Any, **kwargs: Any) -> None:
        pass

    def finish(self) -> None:
        pass

    def save_image(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        # Fallback: silently absorb any other method calls from Manim
        # (like add_partial_movie_file, is_already_cached, etc.)
        def method(*args, **kwargs):
            if name == "is_already_cached":
                return False
            return None
        return method


class _NullSection:
    """Stub for SceneFileWriter.sections entries."""

    skip_animations: bool = False


class HijackedRenderer(OpenGLRenderer):
    """Manim OpenGLRenderer that uses an externally provided OpenGL context.

    Instead of creating its own window (Window mode) or standalone context
    (headless mode), this renderer accepts a ModernGL context from PyQt6's
    QOpenGLWidget via set_external_context().

    This is the "third path" in Manim's init_scene() that the blueprint
    calls the "Zero-Copy FBO Hijack".

    Danger Zone:
        The init_scene() override bypasses Manim's intended initialization.
        The external context MUST be current (active on GPU) when init_scene()
        is called. In PyQt6, this is guaranteed only during paintGL().
    """

    def __init__(self, engine_state: Optional[EngineState] = None, **kwargs: Any) -> None:
        # Use NullFileWriter to prevent all file I/O
        super().__init__(file_writer_class=NullFileWriter, **kwargs)
        self.window = None
        self._external_ctx: moderngl.Context | None = None
        self._engine_state = engine_state
        logger.info("HijackedRenderer created (NullFileWriter active)")

    def set_external_context(self, ctx: moderngl.Context) -> None:
        """Inject the PyQt6 OpenGL context.

        MUST be called before init_scene(). The context must be
        created with moderngl.create_context(standalone=False)
        to adopt PyQt's existing GL context.

        Args:
            ctx: ModernGL context wrapping PyQt's QOpenGLWidget context
        """
        self._external_ctx = ctx
        logger.info(f"External context injected: GL {ctx.version_code}")

    def should_create_window(self) -> bool:
        """NEVER create a Manim window. Always return False.

        This is the first line of defense against rogue windows.
        Even if config['preview'] is True, we suppress it.
        """
        return False

    def init_scene(self, scene: Scene) -> None:
        """Override: Use external PyQt context instead of creating own.

        Original Manim init_scene() has two paths:
            1. Window mode: self.window.ctx + detect_framebuffer()
            2. Headless mode: standalone context + custom FBO

        Our THIRD path:
            3. Hijack mode: external PyQt ctx + detect_framebuffer()

        The key difference from headless mode is:
            - We use standalone=False (adopts existing GL context)
            - We use detect_framebuffer() (gets PyQt's FBO, not our own)
            - No Window object is created

        Args:
            scene: The Manim Scene to initialize rendering for

        Raises:
            RuntimeError: If set_external_context() was not called first
        """
        if self._external_ctx is None:
            raise RuntimeError(
                "External OpenGL context not set! "
                "Call set_external_context(ctx) before init_scene(). "
                "The context must be created inside paintGL() with "
                "moderngl.create_context(standalone=False)."
            )

        # ── Replicate Manim's init_scene() with our context ──

        self.partial_movie_files: list[str | None] = []
        self.file_writer = NullFileWriter(self, scene.__class__.__name__)
        self.scene = scene

        self.background_color = config["background_color"]

        # THE HIJACK: Use external context instead of creating own
        self.context = self._external_ctx

        # detect_framebuffer() returns whatever FBO is currently bound.
        # Inside paintGL(), Qt has bound its internal FBO.
        # This gives us a Framebuffer object pointing to PyQt's VRAM.
        self.frame_buffer_object = self.context.detect_framebuffer()
        self.frame_buffer_object.use()

        # Standard OpenGL state setup (same as Manim's original)
        self.context.enable(moderngl.BLEND)
        self.context.blend_func = (
            moderngl.SRC_ALPHA,
            moderngl.ONE_MINUS_SRC_ALPHA,
            moderngl.ONE,
            moderngl.ONE,
        )

        # Wireframe mode (usually False)
        try:
            self.context.wireframe = config["enable_wireframe"]
        except KeyError:
            self.context.wireframe = False

        logger.info(
            f"Scene initialized with hijacked context. "
            f"FBO viewport: {self.frame_buffer_object.viewport}"
        )

    def update_fbo(self) -> None:
        """Re-detect the framebuffer from the current GL state.

        Called by ManimCanvas in each paintGL() to handle widget
        resizing, where Qt may recreate its internal FBO.

        Safety: detect_framebuffer() is a cheap GL query, not a
        memory allocation. Safe to call every frame.
        """
        if self._external_ctx is not None:
            self.frame_buffer_object = self._external_ctx.detect_framebuffer()

    def update_frame(self, scene: Scene) -> None:
        """Override: Clear hitboxes before rendering, then populate them."""
        # Only rebuild hitboxes when something actually changed (drag, reload, etc.)
        _rebuilding_hitboxes = False
        if self._engine_state is not None and self._engine_state._hitboxes_dirty:
            self._engine_state.clear_hitboxes()
            _rebuilding_hitboxes = True

        # Force should_render = True for ALL mobjects.
        # Manim's update_frame() skips mobjects where should_render is False.
        # ParametricFunction (from axes.plot) has a property that returns False
        # after Create animation modifies points. Writing to __dict__ shadows
        # any property/descriptor on the class, guaranteeing True.
        for mobject in scene.mobjects:
            for sub in mobject.get_family() if hasattr(mobject, 'get_family') else [mobject]:
                try:
                    sub.__dict__['should_render'] = True
                except Exception:
                    pass

        # Call Manim's original update_frame — this calls render_mobject() for each object
        super().update_frame(scene)

        # Mark hitboxes clean AFTER all render_mobject() calls have populated them
        if _rebuilding_hitboxes and self._engine_state is not None:
            self._engine_state._hitboxes_dirty = False

    def _extract_hitbox_single(self, mob: Any) -> None:
        """Extract AABB hitbox for a single mobject (no recursion)."""
        try:
            force_rebuild = getattr(self._engine_state, '_hitboxes_dirty', False)
            needs_new = getattr(mob, 'needs_new_bounding_box', True) or force_rebuild
            if not needs_new and hasattr(mob, '_bisync_hitbox_cache'):
                box = mob._bisync_hitbox_cache
                if box is not None:
                    self._engine_state.push_hitbox(id(mob), box)
            else:
                min_x = float(mob.get_left()[0])
                max_x = float(mob.get_right()[0])
                min_y = float(mob.get_bottom()[1])
                max_y = float(mob.get_top()[1])

                box = None
                if not (np.isnan(min_x) or np.isnan(min_y) or np.isnan(max_x) or np.isnan(max_y)):
                    padding = 0.1
                    box = (min_x - padding, min_y - padding, max_x + padding, max_y + padding)
                    self._engine_state.push_hitbox(id(mob), box)

                mob._bisync_hitbox_cache = box
        except Exception:
            pass

    def _extract_hitbox_recursive(self, mob: Any, depth: int = 0) -> None:
        """Extract AABB hitboxes for a mobject AND its children (depth-limited).

        Only used for the currently isolated mobject so that its internal
        children become individually clickable.
        """
        self._extract_hitbox_single(mob)

        if depth < _HITBOX_MAX_DEPTH:
            subs = getattr(mob, 'submobjects', None)
            if subs:
                for sub in subs:
                    self._extract_hitbox_recursive(sub, depth + 1)

    def render_mobject(self, mobject: OpenGLMobject | OpenGLVMobject) -> None:
        """Override: Render mobject AND extract its AABB for Socket 2."""
        if not hasattr(mobject, "get_shader_wrapper_list"):
            return

        try:
            super().render_mobject(mobject)
        except Exception as e:
            mob_type = type(mobject).__name__
            logger.warning(f"render_mobject failed for {mob_type}: {e}")
            for sub in getattr(mobject, 'submobjects', []):
                try:
                    if hasattr(sub, 'get_shader_wrapper_list'):
                        super().render_mobject(sub)
                except Exception:
                    pass

        # Extract AABB for hit-testing (Socket 2) — only when hitboxes need rebuilding
        if self._engine_state is not None and self._engine_state._hitboxes_dirty:
            mob_key = getattr(mobject, '_bisync_line_number', id(mobject))
            if getattr(self._engine_state, 'isolated_mobject_key', None) == mob_key:
                self._extract_hitbox_recursive(mobject)
            else:
                self._extract_hitbox_single(mobject)
