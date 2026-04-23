"""
Bi-Sync Manim Engine — Main Entry Point
=========================================

Phase 1: Core Rendering & GUI Fusion

Launches a PyQt6 window with a ManimCanvas widget that renders
Manim scenes directly via OpenGL Context Hijack.

Usage:
    python main.py

What should happen:
    1. A single PyQt6 window opens (dark theme)
    2. Blue circle, red square, green dot, and text appear
    3. NO separate Manim/Pyglet window opens
    4. Resizing the window resizes the rendering
"""

from __future__ import annotations

import logging
import sys
import os

# ── Configure Manim BEFORE any Manim imports ──
# This MUST happen before importing Scene, Circle, etc.
# Otherwise Manim may try to create its own window/context.
# LIVE PREVIEW: Uses OpenGL renderer (GPU-accelerated, 60fps)
# EXPORT: Uses Cairo renderer (CPU-based, 100% accurate)
# This "Draft Mode" separation is intentional — live preview is
# for interactive editing, export is for final output.
os.environ["MANIM_RENDERER"] = "opengl"

from manim import config as manim_config

# Headless mode: no preview window, no file output
manim_config.renderer = "opengl"
manim_config.preview = False
manim_config.write_to_movie = False
manim_config.save_last_frame = False
manim_config.disable_caching = True
manim_config.pixel_width = 1920
manim_config.pixel_height = 1080

# ── Monkey-patch Manim 0.19 earcut() type mismatch ──
# The C++ earcut (via mapbox_earcut nanobind) expects ndarray[uint32]
# for the rings parameter, but Manim passes a Python list.
def _patch_manim_earcut():
    """Patch Manim's earcut to handle numpy type conversion."""
    import numpy as np
    import manim.utils.space_ops as space_ops

    original = space_ops.earcut

    def patched(verts, rings):
        if not isinstance(rings, np.ndarray):
            rings = np.array(rings, dtype=np.uint32)
        elif rings.dtype != np.uint32:
            rings = rings.astype(np.uint32)
        if verts.dtype != np.float32:
            verts = verts.astype(np.float32)
        return original(verts, rings)

    space_ops.earcut = patched
    
    # Also patch in modules that hold direct references
    try:
        import manim.mobject.opengl.opengl_vectorized_mobject as _m
        if hasattr(_m, 'earcut'):
            _m.earcut = patched
        if hasattr(_m, 'earclip_triangulation'):
            _m.earclip_triangulation = space_ops.earclip_triangulation
    except ImportError:
        pass

_patch_manim_earcut()

# ── Monkey-patch Mobject to track creation line numbers ──
from manim.mobject.mobject import Mobject
from manim.mobject.opengl.opengl_mobject import OpenGLMobject

_orig_mobject_init = Mobject.__init__
_orig_opengl_mobject_init = OpenGLMobject.__init__

def _patched_mobject_init(self, *args, **kwargs):
    _orig_mobject_init(self, *args, **kwargs)
    try:
        frame = sys._getframe(1)
        while frame:
            # Check if this frame is from a user's scene file
            filename = frame.f_code.co_filename
            if "scenes" in filename and filename.endswith(".py"):
                self._bisync_line_number = frame.f_lineno
                break
            frame = frame.f_back
    except Exception:
        pass

def _patched_opengl_mobject_init(self, *args, **kwargs):
    _orig_opengl_mobject_init(self, *args, **kwargs)
    try:
        frame = sys._getframe(1)
        while frame:
            filename = frame.f_code.co_filename
            if "scenes" in filename and filename.endswith(".py"):
                self._bisync_line_number = frame.f_lineno
                break
            frame = frame.f_back
    except Exception:
        pass

Mobject.__init__ = _patched_mobject_init
OpenGLMobject.__init__ = _patched_opengl_mobject_init


# ── Now safe to import everything else ──

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QSurfaceFormat, QPalette, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QStatusBar,
    QPushButton,
    QToolBar,
    QProgressBar,
    QDialog,
)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

from engine.canvas import ManimCanvas
from engine.state import EngineState
from engine.ast_mutator import ASTMutator
from engine.hot_swap import HotSwapInjector
from engine.file_watcher import SceneFileWatcher
from engine.property_panel import PropertyPanel
from engine.coordinate_transformer import CoordinateTransformer
from engine.hit_tester import HitTester
from engine.drag_controller import DragController
from engine.code_editor import CodeEditorPanel
from engine.animation_player import AnimationPlayer
from engine.export_dialog import ExportDialog, ExportWorker
from scenes.advanced_scene import AdvancedScene

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bisync.main")


def setup_opengl_format() -> None:
    """Configure OpenGL 3.3 Core Profile for the entire application.

    Must be called BEFORE creating QApplication.
    Ensures QOpenGLWidget creates a context compatible with
    Manim's shader requirements (GLSL 330+).
    """
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    # Request 4x MSAA for smooth edges
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
    logger.info("OpenGL 3.3 Core Profile configured")


def apply_dark_theme(app: QApplication) -> None:
    """Apply a dark color palette to the application.

    Matches the typical Manim dark background aesthetic.
    """
    palette = QPalette()

    # Window & base colors
    palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base, QColor(20, 20, 20))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(40, 40, 40))

    # Text colors
    palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(100, 100, 100))

    # Button colors
    palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))

    # Highlights
    palette.setColor(QPalette.ColorRole.Highlight, QColor(70, 130, 180))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))

    app.setPalette(palette)
    logger.info("Dark theme applied")


class MainWindow(QMainWindow):
    """Main application window for the Bi-Sync Manim Engine.

    Phase 4 Architecture (Complete):
        - ManimCanvas (center) — renders Manim scenes
        - PropertyPanel (right dock) — sliders for live property editing
        - AST Mutator — surgical code modification
        - Hot-Swap Injector — exec-based scene reload
        - File Watcher — detects external code changes
        - DragController — mouse drag → mobject move → AST update
        - CoordinateTransformer — pixel → math space
        - HitTester — AABB object selection
    """

    # Path to the scene file (relative to project root)
    SCENE_FILE = "scenes/advanced_scene.py"

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Bi-Sync Manim Engine — Live Editor")
        self.setGeometry(50, 50, 1600, 900)
        self.setMinimumSize(1000, 600)

        # ── Engine State ──
        self.engine_state = EngineState()

        # ── AST Mutator ──
        self.ast_mutator = ASTMutator()
        scene_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), self.SCENE_FILE
        )
        self.ast_mutator.parse_file(scene_path)

        # ── Coordinate Transformer (Phase 4) ──
        self.coord_transformer = CoordinateTransformer()

        # ── Hit Tester (Phase 4) ──
        self.hit_tester = HitTester(self.engine_state, self.ast_mutator)

        # ── Central Widget Layout ──
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Animation Player ──
        self.animation_player = AnimationPlayer(fps=60)

        # ── Manim Canvas ──
        self.canvas = ManimCanvas(
            scene_class=AdvancedScene,
            engine_state=self.engine_state,
            parent=central,
        )
        # Wire animation player to canvas BEFORE first paint
        self.canvas.set_animation_player(self.animation_player)
        self.canvas.set_ast_mutator(self.ast_mutator)
        layout.addWidget(self.canvas)
        self.setCentralWidget(central)

        # ── Hot-Swap Injector ──
        self.hot_swap = HotSwapInjector(self.engine_state)
        self.hot_swap.set_ast_mutator(self.ast_mutator)

        # ── File Watcher ──
        self.file_watcher = SceneFileWatcher(
            engine_state=self.engine_state,
            on_file_changed=self._on_file_changed,
        )
        self.file_watcher.watch(scene_path)

        # ── Drag Controller (Phase 4) ──
        self.drag_controller = DragController(
            engine_state=self.engine_state,
            hit_tester=self.hit_tester,
            coord_transformer=self.coord_transformer,
            ast_mutator=self.ast_mutator,
            file_watcher=self.file_watcher,
        )

        # Wire drag controller and coord transformer to canvas
        self.canvas.set_drag_controller(self.drag_controller)
        self.canvas.set_coord_transformer(self.coord_transformer)

        # ── Property Panel (Right Dock) ──
        self.property_panel = PropertyPanel(
            engine_state=self.engine_state,
            ast_mutator=self.ast_mutator,
            hot_swap=self.hot_swap,
            file_watcher=self.file_watcher,
            parent=self,
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_panel)

        # Wire transform drag to full reload
        self.property_panel.transform_drag_requested.connect(self._on_transform_drag_requested)
        self._transform_drag_timer = QTimer()
        self._transform_drag_timer.setSingleShot(True)
        self._transform_drag_timer.setInterval(200) # 200ms debounce
        self._transform_drag_timer.timeout.connect(self._execute_debounced_transform_reload)
        self._pending_transform: Optional[tuple[str, str, float]] = None

        # ── Code Editor (Left Dock) ──
        self.code_editor = CodeEditorPanel(
            scene_file=scene_path,
            engine_state=self.engine_state,
            file_watcher=self.file_watcher,
            parent=self,
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.code_editor)

        # ── State Reconciliation: sync BOTH sliders AND code editor ──
        self.engine_state.on_gui_update(self.property_panel.sync_from_code)
        self.engine_state.on_gui_update(self.code_editor.sync_from_file)

        # ── Wire Code Editor → Full Reload Pipeline ──
        # When user types code → save → THIS triggers AST + hot-swap + sliders
        self.code_editor.set_on_code_saved(self._on_code_editor_saved)

        # ── Animation Toolbar ──
        self._build_animation_toolbar()

        # ── Status Bar ──
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(
            "Bi-Sync Active | Code Editor | Canvas | Animations | Drag & Drop"
        )

        # Wire hot-swap + drag to canvas (deferred until canvas initializes)
        self._scene_path = scene_path
        self.engine_state.on_scene_parsed(self._on_scene_ready)

        logger.info("MainWindow created (Bi-Sync: Full Two-Panel)")

    def _on_scene_ready(self) -> None:
        """Called after ManimCanvas constructs the scene.

        Wires hot-swap, drag controller, and animation player to the live scene.
        """
        scene = self.canvas.get_scene()
        if scene is not None:
            self.hot_swap.set_scene(scene, self._scene_path)
            self.drag_controller.set_scene(scene)
            self.animation_player.set_scene(scene)

            # Update coord transformer with initial widget size
            self.coord_transformer.set_widget_size(
                self.canvas.width(), self.canvas.height()
            )

            # Update status bar with animation count
            anim_count = self.animation_player.animation_count
            self.status_bar.showMessage(
                f"Bi-Sync Active | {anim_count} animations captured | "
                f"Press ▶ Play to animate"
            )

            logger.info(
                f"All controllers connected. "
                f"{anim_count} animations ready."
            )

    # Module name for importlib.reload
    SCENE_MODULE = "scenes.advanced_scene"

    def _on_file_changed(self, path: str) -> None:
        """Called by file watcher when scene file changes externally.

        Smart detection:
            - Compare old vs new AST bindings
            - Same structure → property-only update (fast)
            - Different structure → full scene reload (slow but complete)
        """
        logger.info(f"External file change detected: {os.path.basename(path)}")

        # Save old binding keys for comparison
        old_binding_keys = set(self.ast_mutator.bindings.keys())

        # Re-parse AST
        self.ast_mutator.parse_file(path)
        new_binding_keys = set(self.ast_mutator.bindings.keys())

        # Detect structural change or recover from unhealthy state
        if old_binding_keys != new_binding_keys or not self.engine_state.scene_is_healthy:
            logger.info(
                f"STRUCTURAL CHANGE detected: "
                f"old={old_binding_keys}, new={new_binding_keys}, "
                f"healthy={self.engine_state.scene_is_healthy}"
            )
            self._do_full_reload(path)
        else:
            # Fast path: property-only update
            self._do_property_update()

        # Sync code editor (ghost-typing effect)
        self.code_editor.sync_from_file()

        self.engine_state.request_render()

    def _on_code_editor_saved(self, path: str) -> None:
        """Called when user types code in the editor and debounce saves.

        Same smart detection as _on_file_changed.
        Does NOT sync code editor back (prevents feedback loop).
        """
        logger.info(f"Code Editor save → reloading: {os.path.basename(path)}")

        old_binding_keys = set(self.ast_mutator.bindings.keys())

        self.ast_mutator.parse_file(path)
        new_binding_keys = set(self.ast_mutator.bindings.keys())

        # Detect structural change or recover from unhealthy state
        if old_binding_keys != new_binding_keys or not self.engine_state.scene_is_healthy:
            logger.info(
                f"STRUCTURAL CHANGE from editor: "
                f"old={old_binding_keys}, new={new_binding_keys}, "
                f"healthy={self.engine_state.scene_is_healthy}"
            )
            self._do_full_reload(path)
        else:
            self._do_property_update()
            self.property_panel.sync_from_code()

        self.engine_state.request_render()
        logger.info("Code change processed")

    def _do_property_update(self) -> None:
        """Fast path: apply property changes to existing mobjects.

        Passes ALL property types (numbers, colors, strings) to hot_swap.
        """
        all_props = self.ast_mutator.get_all_properties()
        for var_name, props in all_props.items():
            for prop_name, value in props.items():
                if value is not None:
                    self.hot_swap.apply_single_property(
                        var_name, prop_name, value
                    )

        self.engine_state.emit_gui_update()
        logger.info("Property-only update applied")

    def _do_full_reload(self, path: str) -> None:
        """Slow path: full scene reload via importlib.reload.

        Destroys old scene, re-imports module, constructs new scene.
        Then re-wires all controllers to the new scene.
        """
        logger.info("Starting FULL SCENE RELOAD...")

        # Clear live binds before reload
        self.ast_mutator._live_binds.clear()
        self.animation_player.reset()

        success = self.canvas.reload_scene_from_module(
            self.SCENE_MODULE, path
        )

        if success:
            # Re-wire all controllers to the new scene
            scene = self.canvas.get_scene()
            if scene is not None:
                self.hot_swap.set_scene(scene, self._scene_path)
                self.drag_controller.set_scene(scene)
                self.animation_player.set_scene(scene)

                self.coord_transformer.set_widget_size(
                    self.canvas.width(), self.canvas.height()
                )

                # Sync sliders from new code
                self.property_panel.sync_from_code()

                anim_count = self.animation_player.animation_count
                self.status_bar.showMessage(
                    f"Scene reloaded | {len(scene.mobjects)} objects | "
                    f"{anim_count} animations"
                )
                logger.info("Full reload complete — all controllers re-wired")
        else:
            logger.error("Full reload FAILED — scene unchanged")
            self.status_bar.showMessage("⚠ Scene reload failed")

    def _on_transform_drag_requested(self, target_var: str, method_name: str, value: float) -> None:
        """Handle transform drag with debouncing to avoid freezing."""
        self._pending_transform = (target_var, method_name, value)
        self._transform_drag_timer.start()

    def _execute_debounced_transform_reload(self) -> None:
        """Apply the pending transform and perform a full reload safely."""
        if not self._pending_transform:
            return
            
        target_var, method_name, value = self._pending_transform
        self._pending_transform = None
        
        # AST surgery: modify source code in memory
        self.ast_mutator.update_transform_method(target_var, method_name, value)
        
        scene_file = self.ast_mutator._file_path
        if scene_file:
            self.ast_mutator.save_atomic()
            # Fast update for transform changes instead of full reload to prevent flicker
            self._do_full_reload(str(scene_file))

    # ────────────────────────────────────────────────────────────
    # Animation Toolbar
    # ────────────────────────────────────────────────────────────

    def _build_animation_toolbar(self) -> None:
        """Build the animation playback toolbar at the top."""
        from PyQt6.QtWidgets import QSlider
        
        toolbar = QToolBar("Animation Controls")
        toolbar.setMovable(False)
        toolbar.setStyleSheet("""
            QToolBar {
                background: #21252b;
                border-bottom: 1px solid #181a1f;
                padding: 4px 8px;
                spacing: 6px;
            }
        """)

        btn_style = """
            QPushButton {
                background: #3a3f4b;
                color: #abb2bf;
                border: 1px solid #4b5263;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background: #4b5263;
                border-color: #61afef;
            }
            QPushButton:pressed {
                background: #61afef;
                color: #282c34;
            }
            QPushButton:disabled {
                background: #2c313a;
                color: #5c6370;
                border-color: #3a3f4b;
            }
        """

        # Play button
        self._btn_play = QPushButton("▶  Play")
        self._btn_play.setStyleSheet(btn_style)
        self._btn_play.clicked.connect(self._on_play_clicked)
        toolbar.addWidget(self._btn_play)

        # Pause button
        self._btn_pause = QPushButton("⏸  Pause")
        self._btn_pause.setStyleSheet(btn_style)
        self._btn_pause.setEnabled(False)
        self._btn_pause.clicked.connect(self._on_pause_clicked)
        toolbar.addWidget(self._btn_pause)

        # Reset button
        self._btn_reset = QPushButton("🔄 Reset")
        self._btn_reset.setStyleSheet(btn_style)
        self._btn_reset.clicked.connect(self._on_reset_clicked)
        toolbar.addWidget(self._btn_reset)

        # Save button
        self._btn_save = QPushButton("💾 Save")
        self._btn_save.setStyleSheet(btn_style)
        self._btn_save.clicked.connect(self._on_save_clicked)
        toolbar.addWidget(self._btn_save)

        # Refresh button (cyan — forces full scene reload)
        self._btn_refresh = QPushButton("⟳  Refresh")
        self._btn_refresh.setStyleSheet("""
            QPushButton {
                background: #1a3a4a;
                color: #56b6c2;
                border: 1px solid #2a5a6a;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background: #2a5a6a;
                border-color: #56b6c2;
            }
            QPushButton:pressed {
                background: #56b6c2;
                color: #282c34;
            }
        """)
        self._btn_refresh.clicked.connect(self._on_refresh_clicked)
        toolbar.addWidget(self._btn_refresh)

        # Separator
        sep = QWidget()
        sep.setFixedWidth(2)
        sep.setStyleSheet("background: #3a3f4b;")
        toolbar.addWidget(sep)

        # Export button (special green style)
        self._btn_export = QPushButton("📹  Export")
        self._btn_export.setStyleSheet("""
            QPushButton {
                background: #2d5a3d;
                color: #98c379;
                border: 1px solid #3d7a53;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background: #3d7a53;
                border-color: #98c379;
            }
            QPushButton:pressed {
                background: #98c379;
                color: #282c34;
            }
        """)
        self._btn_export.clicked.connect(self._on_export_clicked)
        toolbar.addWidget(self._btn_export)

        # Spacer
        spacer = QWidget()
        spacer.setFixedWidth(16)
        toolbar.addWidget(spacer)

        # View Toggles
        self._btn_toggle_code = QPushButton("📝 Code")
        self._btn_toggle_code.setCheckable(True)
        self._btn_toggle_code.setChecked(True)
        self._btn_toggle_code.setStyleSheet(btn_style)
        self._btn_toggle_code.toggled.connect(self._on_toggle_code)
        toolbar.addWidget(self._btn_toggle_code)

        self._btn_toggle_props = QPushButton("⚙️ Props")
        self._btn_toggle_props.setCheckable(True)
        self._btn_toggle_props.setChecked(True)
        self._btn_toggle_props.setStyleSheet(btn_style)
        self._btn_toggle_props.toggled.connect(self._on_toggle_props)
        toolbar.addWidget(self._btn_toggle_props)

        # Spacer
        spacer2 = QWidget()
        spacer2.setFixedWidth(16)
        toolbar.addWidget(spacer2)

        # Scrubber / Timeline slider
        self._progress_slider = QSlider(Qt.Orientation.Horizontal)
        self._progress_slider.setRange(0, 1000)
        self._progress_slider.setValue(0)
        self._progress_slider.setFixedHeight(20)
        self._progress_slider.setMinimumWidth(300)
        self._progress_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #2c313a;
                border: 1px solid #3a3f4b;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #61afef, stop:1 #c678dd
                );
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #abb2bf;
                width: 14px;
                height: 14px;
                margin: -3px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffffff;
            }
        """)
        # Connect slider drag to seek function
        self._progress_slider.valueChanged.connect(self._on_timeline_scrub)
        toolbar.addWidget(self._progress_slider)

        # Animation label
        self._anim_label = QLabel("  Ready")
        self._anim_label.setStyleSheet(
            "color: #5c6370; font-size: 12px; padding: 0 8px;"
        )
        toolbar.addWidget(self._anim_label)

        self.addToolBar(toolbar)

        # Wire callbacks from animation player
        self.animation_player.set_on_state_changed(self._on_anim_state_changed)
        self.animation_player.set_on_progress_changed(self._on_anim_progress)

    def _on_timeline_scrub(self, value: int) -> None:
        """Called when user drags the timeline scrubber."""
        if not self._progress_slider.isSliderDown():
            return

        progress = value / 1000.0
        self.animation_player.seek(progress)

        total_anims = len(self.ast_mutator.animations)
        if total_anims == 0:
            self.engine_state.selected_animation = None
            return

        # Use total_anims consistently, not animation_count
        anim_idx = int(progress * total_anims)
        anim_idx = max(0, min(anim_idx, total_anims - 1))  # Clamp to valid range

        self.engine_state.selected_animation = self.ast_mutator.animations[anim_idx]
        self.engine_state.request_render()

    def _on_play_clicked(self) -> None:
        self.animation_player.play()

    def _on_pause_clicked(self) -> None:
        self.animation_player.pause()

    def _on_reset_clicked(self) -> None:
        self.animation_player.reset()
        self._progress_slider.blockSignals(True)
        self._progress_slider.setValue(0)
        self._progress_slider.blockSignals(False)
        self._anim_label.setText("  Reset — press ▶ Play")

    def _on_save_clicked(self) -> None:
        """Manually trigger AST atomic save."""
        self.ast_mutator.save_atomic()
        self.status_bar.showMessage("💾 Code saved to disk")
        logger.info("Manual save requested")

    def _on_refresh_clicked(self) -> None:
        """Force full scene reload from disk."""
        logger.info("⟳ Manual refresh requested")
        self.ast_mutator.parse_file(self._scene_path)
        self._do_full_reload(self._scene_path)
        self.code_editor.sync_from_file()
        self.engine_state.request_render()
        self.status_bar.showMessage("⟳ Scene refreshed")

    def _on_toggle_code(self, checked: bool) -> None:
        """Toggle the visibility of the Code Editor panel."""
        self.code_editor.setVisible(checked)
        self._btn_toggle_code.setStyleSheet(
            self._btn_toggle_code.styleSheet().replace(
                "background: #61afef;" if not checked else "background: #3a3f4b;",
                "background: #3a3f4b;" if not checked else "background: #61afef;"
            ) # Basic indication, QDockWidget handles visibility internally
        )

    def _on_toggle_props(self, checked: bool) -> None:
        """Toggle the visibility of the Property panel."""
        self.property_panel.setVisible(checked)

    def _on_anim_state_changed(self, state: str) -> None:
        """Update toolbar buttons based on animation state."""
        is_playing = state == self.animation_player.PLAYING
        is_idle = state == self.animation_player.IDLE

        self._btn_play.setEnabled(not is_playing)
        self._btn_pause.setEnabled(is_playing)

        if is_playing:
            self._btn_play.setText("▶  Playing...")
            self._anim_label.setText("  ▶ Animating...")
        elif state == self.animation_player.PAUSED:
            self._btn_play.setText("▶  Resume")
            self._anim_label.setText("  ⏸ Paused")
        elif is_idle:
            self._btn_play.setText("▶  Play")
            count = self.animation_player.animation_count
            if self.animation_player.progress >= 1.0:
                self._anim_label.setText(f"  ✅ Complete ({count} animations)")
            else:
                self._anim_label.setText(f"  Ready ({count} animations)")

    def _on_anim_progress(self, progress: float) -> None:
        """Update progress slider during animation."""
        if not self._progress_slider.isSliderDown():
            self._progress_slider.blockSignals(True)
            self._progress_slider.setValue(int(progress * 1000))
            self._progress_slider.blockSignals(False)

    # ────────────────────────────────────────────────────────────
    # Video Export
    # ────────────────────────────────────────────────────────────

    def _on_export_clicked(self) -> None:
        """Show export dialog and start rendering."""
        dialog = ExportDialog(self._scene_path, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            settings = dialog.get_settings()
            self._start_export(settings)

    def _start_export(self, settings: dict) -> None:
        """Launch background export worker."""
        logger.info(
            f"Export started: {settings['resolution_name']} @ "
            f"{settings['fps']}fps ({settings['format']})"
        )

        # Update UI
        self._btn_export.setEnabled(False)
        self._btn_export.setText("📹  Exporting...")
        self._progress_slider.blockSignals(True)
        self._progress_slider.setValue(0)
        self._progress_slider.blockSignals(False)
        self._anim_label.setText("  📹 Rendering video...")

        # Start background worker
        self._export_worker = ExportWorker(settings)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.start()

    def _on_export_progress(self, percent: int, message: str) -> None:
        self._progress_slider.blockSignals(True)
        self._progress_slider.setValue(percent * 10)
        self._progress_slider.blockSignals(False)
        self._anim_label.setText(f"  {message}")

    def _on_export_finished(self, output_path: str) -> None:
        self._btn_export.setEnabled(True)
        self._btn_export.setText("📹  Export")
        self._progress_slider.blockSignals(True)
        self._progress_slider.setValue(1000)
        self._progress_slider.blockSignals(False)
        self._anim_label.setText("  ✅ Export complete!")

        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Export Complete",
            f"Video exported successfully!\n\n{output_path}",
        )
        logger.info(f"Export complete: {output_path}")

    def _on_export_error(self, error_msg: str) -> None:
        self._btn_export.setEnabled(True)
        self._btn_export.setText("📹  Export")
        self._progress_slider.blockSignals(True)
        self._progress_slider.setValue(0)
        self._progress_slider.blockSignals(False)
        self._anim_label.setText("  ❌ Export failed")

        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Export Failed", error_msg)
        logger.error(f"Export failed: {error_msg}")


def main() -> None:
    """Entry point for the Bi-Sync Manim Engine."""

    logger.info("═══════════════════════════════════════════")
    logger.info("  Bi-Sync Manim Engine — Phase 3 Starting  ")
    logger.info("═══════════════════════════════════════════")

    # Step 1: Configure OpenGL BEFORE QApplication
    setup_opengl_format()

    # Step 2: Create Qt Application
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    # Step 3: Create and show main window
    window = MainWindow()
    window.show()

    logger.info("Window shown — entering Qt event loop")

    # Step 4: Run event loop
    exit_code = app.exec()

    logger.info(f"Application exited with code: {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
