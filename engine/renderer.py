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
        """Override: Clear hitboxes before rendering, then populate them.

        Extends Manim's update_frame to:
        1. Clear Socket 2 hitbox dict at frame start
        2. Call parent update_frame (which calls render_mobject per object)
        3. Hitboxes are populated by our render_mobject override
        """
        # Clear hitboxes for this frame
        if self._engine_state is not None:
            self._engine_state.clear_hitboxes()

        # Call Manim's original update_frame
        # (which calls render_mobject for each visible mobject)
        super().update_frame(scene)

    def render_mobject(self, mobject: OpenGLMobject | OpenGLVMobject) -> None:
        """Override: Render mobject AND extract its AABB for Socket 2.

        After Manim renders the mobject's shaders, we compute its
        Axis-Aligned Bounding Box (AABB) in Manim math coordinates
        and push it to EngineState.push_hitbox().

        Phase 3's Mouse Ray-Caster will use these hitboxes for
        click detection without expensive mesh intersection.

        The AABB is computed from the mobject's points array,
        which is already in Manim's coordinate space.
        """
        # Let Manim do the actual GPU rendering
        super().render_mobject(mobject)

        # Extract AABB for hit-testing (Socket 2)
        if self._engine_state is not None:
            try:
                # Always prefer get_bounding_box for comprehensive hitboxes 
                # (works for Text, VGroups, and complex leaf nodes)
                bb = mobject.get_bounding_box()
                if bb is not None and len(bb) == 3:
                    import numpy as np
                    min_x, min_y = float(bb[0][0]), float(bb[0][1])
                    max_x, max_y = float(bb[2][0]), float(bb[2][1])
                    
                    # Ignore invalid or empty bounding boxes
                    if not (np.isnan(min_x) or np.isnan(min_y) or np.isnan(max_x) or np.isnan(max_y)):
                        # Expand hitbox slightly for easier clicking on thin objects (like text or lines)
                        padding = 0.1
                        self._engine_state.push_hitbox(
                            id(mobject),
                            (min_x - padding, min_y - padding, max_x + padding, max_y + padding),
                        )
            except Exception:
                # Don't let hitbox extraction crash the render pipeline
                pass
