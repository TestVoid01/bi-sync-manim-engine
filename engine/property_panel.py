"""
Bi-Sync Property Panel — PyQt Slider UI
=========================================

Phase 3: Bi-Directional Sync Bridge

A dock widget with sliders for controlling Manim scene properties.
Each slider change triggers the AST Mutator → File Save → Hot-Swap
pipeline for GUI→Code synchronization.

During drag (continuous slider movement):
    - In-memory update only (fast path via HotSwapInjector.apply_single_property)
    - File watcher is paused to prevent feedback loop

On slider release:
    - AST Mutator saves atomically to disk
    - File watcher resumes
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDockWidget,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

logger = logging.getLogger("bisync.property_panel")

if TYPE_CHECKING:
    from engine.ast_mutator import ASTMutator
    from engine.file_watcher import SceneFileWatcher
    from engine.hot_swap import HotSwapInjector
    from engine.state import EngineState


MANIM_SCHEMA = {
    "Circle": {
        "radius": 1.0,
        "color": "WHITE",
        "fill_opacity": 0.0,
        "stroke_width": 4.0,
        "stroke_opacity": 1.0,
    },
    "Square": {
        "side_length": 2.0,
        "color": "WHITE",
        "fill_opacity": 0.0,
        "stroke_width": 4.0,
        "stroke_opacity": 1.0,
    },
    "Rectangle": {
        "width": 4.0,
        "height": 2.0,
        "color": "WHITE",
        "fill_opacity": 0.0,
        "stroke_width": 4.0,
        "stroke_opacity": 1.0,
    },
    "Triangle": {
        "color": "WHITE",
        "fill_opacity": 0.0,
        "stroke_width": 4.0,
        "stroke_opacity": 1.0,
    },
    "Line": {
        "color": "WHITE",
        "stroke_width": 4.0,
        "stroke_opacity": 1.0,
    },
    "Axes": {
        "x_range": [-10.0, 10.0, 1.0],
        "y_range": [-10.0, 10.0, 1.0],
        "x_length": 10.0,
        "y_length": 10.0,
    },
    "Tex": {
        "color": "WHITE",
        "fill_opacity": 1.0,
    },
    "MathTex": {
        "color": "WHITE",
        "fill_opacity": 1.0,
    },
}

DEFAULT_VMOBJECT_SCHEMA = {
    "color": "WHITE",
    "fill_opacity": 0.0,
    "stroke_width": 4.0,
    "stroke_opacity": 1.0,
}


class PropertyString(QWidget):
    """A labeled text input for string properties.
    
    Emits signals for both continuous updates (typing) and
    final updates (losing focus / pressing enter).
    """

    value_changed = pyqtSignal(str)
    value_released = pyqtSignal(str)

    def __init__(
        self,
        label: str,
        initial: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        # Label
        self._label = QLabel(label)
        self._label.setFixedWidth(100)
        self._label.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(self._label)

        # Text Input
        self._input = QLineEdit(str(initial))
        self._input.setStyleSheet("""
            QLineEdit {
                background: #333;
                color: #fff;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 2px 4px;
            }
        """)
        layout.addWidget(self._input, stretch=1)

        # Connect signals
        self._input.textChanged.connect(self._on_changed)
        self._input.editingFinished.connect(self._on_released)

    def _on_changed(self, text: str) -> None:
        self.value_changed.emit(text)

    def _on_released(self) -> None:
        self.value_released.emit(self._input.text())

    def set_value(self, value: str) -> None:
        self._input.blockSignals(True)
        self._input.setText(str(value))
        self._input.blockSignals(False)


class PropertySlider(QWidget):
    """A labeled slider with value display.

    Emits signals for both continuous updates (drag) and
    final updates (release).
    """

    value_changed = pyqtSignal(float)  # Continuous during drag
    value_released = pyqtSignal(float)  # On mouse release

    def __init__(
        self,
        label: str,
        min_val: float,
        max_val: float,
        initial: float,
        step: float = 0.1,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._min = min_val
        self._max = max_val
        self._step = step

        # Convert float range to integer range for QSlider
        self._multiplier = int(1.0 / step)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        # Label
        self._label = QLabel(label)
        self._label.setFixedWidth(100)
        self._label.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(self._label)

        # Slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(int(min_val * self._multiplier))
        self._slider.setMaximum(int(max_val * self._multiplier))
        self._slider.setValue(int(initial * self._multiplier))
        self._slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #4a90d9;
                width: 14px;
                height: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #5ba0e9;
            }
        """)
        layout.addWidget(self._slider, stretch=1)

        # Value display
        self._value_label = QLabel(f"{initial:.1f}")
        self._value_label.setFixedWidth(40)
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._value_label.setStyleSheet("color: #4a90d9; font-size: 12px; font-weight: bold;")
        layout.addWidget(self._value_label)

        # Connect signals
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._slider.sliderReleased.connect(self._on_slider_released)

    def _on_slider_changed(self, int_value: int) -> None:
        """Continuous update during drag."""
        value = int_value / self._multiplier
        self._value_label.setText(f"{value:.1f}")
        self.value_changed.emit(value)

    def _on_slider_released(self) -> None:
        """Final update on mouse release."""
        value = self._slider.value() / self._multiplier
        self.value_released.emit(value)

    def set_value(self, value: float) -> None:
        """Programmatically set the slider value (for state reconciliation).

        Blocks signals to prevent feedback loop.
        """
        self._slider.blockSignals(True)
        self._slider.setValue(int(value * self._multiplier))
        self._value_label.setText(f"{value:.1f}")
        self._slider.blockSignals(False)

    def get_value(self) -> float:
        """Get the current slider value."""
        return self._slider.value() / self._multiplier


class PropertyDropdown(QWidget):
    """A labeled dropdown menu (QComboBox) for string selection.

    Emits signal when selection changes.
    """

    value_changed = pyqtSignal(str)

    def __init__(
        self,
        label: str,
        options: list[str],
        initial: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        # Label
        self._label = QLabel(label)
        self._label.setFixedWidth(100)
        self._label.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(self._label)

        from PyQt6.QtWidgets import QComboBox
        # Dropdown
        self._combo = QComboBox()
        self._combo.addItems(options)
        if initial in options:
            self._combo.setCurrentText(initial)
        else:
            self._combo.addItem(initial)
            self._combo.setCurrentText(initial)
            
        self._combo.setStyleSheet("""
            QComboBox {
                background: #333;
                color: #fff;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 2px 4px;
            }
            QComboBox::drop-down {
                border-left: 1px solid #555;
            }
        """)
        layout.addWidget(self._combo, stretch=1)

        # Connect signals
        self._combo.currentTextChanged.connect(self._on_changed)

    def _on_changed(self, text: str) -> None:
        self.value_changed.emit(text)

    def set_value(self, value: str) -> None:
        self._combo.blockSignals(True)
        if self._combo.findText(value) == -1:
            self._combo.addItem(value)
        self._combo.setCurrentText(value)
        self._combo.blockSignals(False)


class PropertyPanel(QDockWidget):
    """Dock widget containing dynamic property sliders for scene manipulation.

    Phase 6.1: Dynamic Property Inspector
    Two-way sync:
        GUI → Code: Slider change → AST Mutator → file save
        Code → GUI: File change → parse → update sliders
    """

    def __init__(
        self,
        engine_state: EngineState,
        ast_mutator: ASTMutator,
        hot_swap: HotSwapInjector,
        file_watcher: Optional[SceneFileWatcher] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__("Properties", parent)

        self._engine_state = engine_state
        self._ast_mutator = ast_mutator
        self._hot_swap = hot_swap
        self._file_watcher = file_watcher

        # Store dynamic sliders {prop_name: PropertySlider}
        self._dynamic_sliders: dict[str, PropertySlider] = {}
        self._current_var_name: Optional[str] = None

        # Don't allow closing
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        from PyQt6.QtWidgets import QScrollArea
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setStyleSheet("QScrollArea { border: none; }")
        
        self._container = QWidget()
        self._main_layout = QVBoxLayout(self._container)
        self._main_layout.setContentsMargins(8, 8, 8, 8)
        self._main_layout.setSpacing(12)

        # Title
        self._title = QLabel("Scene Properties")
        self._title.setStyleSheet(
            "color: #fff; font-size: 14px; font-weight: bold; padding: 4px 0;"
        )
        self._main_layout.addWidget(self._title)

        # Dynamic Content Layout
        self._content_layout = QVBoxLayout()
        self._main_layout.addLayout(self._content_layout)

        # Spacer
        self._main_layout.addStretch()

        self._scroll_area.setWidget(self._container)
        self.setWidget(self._scroll_area)
        self.setMinimumWidth(260)

        # Listen for selection changes
        self._engine_state.on_selection_changed(self._on_selection_changed)

        logger.info("PropertyPanel initialized (Dynamic Mode)")

    def _on_selection_changed(self, var_name: Optional[str]) -> None:
        """Triggered when user clicks an object in the canvas."""
        self._current_var_name = var_name
        self._build_dynamic_ui()

    def _build_dynamic_ui(self) -> None:
        """Clear existing UI and build sliders based on the selected object's AST kwargs."""
        # Clear existing dynamic widgets
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self._dynamic_sliders.clear()

        if not self._current_var_name:
            self._title.setText("Scene Properties (No Selection)")
            return

        # Fetch AST properties for this variable
        ref = self._ast_mutator.get_binding_by_name(self._current_var_name)
        if not ref:
            self._title.setText(f"Scene Properties (Unknown: {self._current_var_name})")
            return

        self._title.setText(f"Properties: {self._current_var_name} ({ref.constructor_name})")

        ast_props = ref.properties
        schema_props = MANIM_SCHEMA.get(ref.constructor_name, DEFAULT_VMOBJECT_SCHEMA).copy()
        
        # Merge: Start with schema, override with anything actually written in code
        props = schema_props.copy()
        props.update(ast_props)

        if not props:
            lbl = QLabel("No numerical or string properties found.")
            lbl.setStyleSheet("color: #888;")
            self._content_layout.addWidget(lbl)
            return

        # Build UI for numerical properties
        # Basic heuristic ranges for Manim properties
        ranges = {
            "radius": (0.1, 10.0),
            "side_length": (0.1, 10.0),
            "width": (0.1, 15.0),
            "height": (0.1, 15.0),
            "stroke_width": (0.0, 20.0),
            "fill_opacity": (0.0, 1.0),
            "stroke_opacity": (0.0, 1.0),
            "x_range": (-20.0, 20.0), # Example defaults
            "y_range": (-20.0, 20.0),
        }

        for prop_name, value in props.items():
            if isinstance(value, (int, float)):
                # Determine min/max range
                min_val, max_val = ranges.get(prop_name, (value - 10.0, value + 10.0))
                if value < min_val: min_val = float(value) - 5.0
                if value > max_val: max_val = float(value) + 5.0
                if min_val == max_val: max_val += 1.0
                
                # Special cases
                if "opacity" in prop_name:
                    min_val, max_val = 0.0, 1.0
                elif "width" in prop_name or "radius" in prop_name or "length" in prop_name:
                    min_val = max(0.0, min_val)

                slider = PropertySlider(
                    label=prop_name,
                    min_val=min_val,
                    max_val=max_val,
                    initial=float(value)
                )
                
                slider.value_changed.connect(
                    lambda v, v_name=self._current_var_name, p_name=prop_name: 
                        self._on_drag(v_name, p_name, v)
                )
                slider.value_released.connect(
                    lambda v, v_name=self._current_var_name, p_name=prop_name: 
                        self._on_release(v_name, p_name, v)
                )

                self._content_layout.addWidget(slider)
                self._dynamic_sliders[prop_name] = slider

            elif isinstance(value, str):
                str_input = PropertyString(
                    label=prop_name,
                    initial=value
                )

                str_input.value_changed.connect(
                    lambda text, v_name=self._current_var_name, p_name=prop_name: 
                        self._on_drag(v_name, p_name, text)
                )
                str_input.value_released.connect(
                    lambda text, v_name=self._current_var_name, p_name=prop_name: 
                        self._on_release(v_name, p_name, text)
                )

                self._content_layout.addWidget(str_input)
                # Store it in dynamic sliders dict for code sync
                self._dynamic_sliders[prop_name] = str_input

        # ---------------------------------------------------------------------
        # Transform Section (Scale, Rotate)
        # ---------------------------------------------------------------------
        transform_group = QGroupBox("Transforms")
        transform_group.setStyleSheet("QGroupBox { color: #aaa; font-weight: bold; padding-top: 15px; }")
        transform_layout = QVBoxLayout(transform_group)
        
        # Scale Slider
        scale_val = ref.transforms.get("scale", 1.0)
        scale_slider = PropertySlider(label="scale", min_val=0.1, max_val=10.0, initial=float(scale_val))
        scale_slider.value_changed.connect(
            lambda v, v_name=self._current_var_name: self._on_transform_drag(v_name, "scale", v)
        )
        scale_slider.value_released.connect(
            lambda v, v_name=self._current_var_name: self._on_transform_release(v_name, "scale", v)
        )
        transform_layout.addWidget(scale_slider)
        self._dynamic_sliders["_scale"] = scale_slider # special key for syncing
        
        # Rotate Slider
        import math
        rotate_val = ref.transforms.get("rotate", 0.0)
        rotate_slider = PropertySlider(label="rotate", min_val=-math.pi*2, max_val=math.pi*2, initial=float(rotate_val))
        rotate_slider.value_changed.connect(
            lambda v, v_name=self._current_var_name: self._on_transform_drag(v_name, "rotate", v)
        )
        rotate_slider.value_released.connect(
            lambda v, v_name=self._current_var_name: self._on_transform_release(v_name, "rotate", v)
        )
        transform_layout.addWidget(rotate_slider)
        self._dynamic_sliders["_rotate"] = rotate_slider
        
        self._content_layout.addWidget(transform_group)

        # ---------------------------------------------------------------------
        # Animation Section
        # ---------------------------------------------------------------------
        # Find if this target has an animation
        target_anim = None
        for anim in self._ast_mutator.animations:
            if anim.target_var == self._current_var_name:
                target_anim = anim
                break
                
        if target_anim:
            anim_group = QGroupBox("Animation")
            anim_group.setStyleSheet("QGroupBox { color: #aaa; font-weight: bold; padding-top: 15px; }")
            anim_layout = QVBoxLayout(anim_group)
            
            # Animation Type Dropdown
            anim_effects = ["Create", "Write", "FadeIn", "FadeOut", "GrowFromCenter", "SpinInFromNothing", "DrawBorderThenFill"]
            # Try to map lowercase AST names back to proper case if possible, else just use what's there
            current_effect = next((e for e in anim_effects if e.lower() == target_anim.method_name.lower()), target_anim.method_name)
            
            anim_dropdown = PropertyDropdown(label="Effect", options=anim_effects, initial=current_effect)
            anim_dropdown.value_changed.connect(
                lambda text, v_name=self._current_var_name, old_eff=target_anim.method_name: 
                    self._on_animation_type_change(v_name, old_eff, text)
            )
            anim_layout.addWidget(anim_dropdown)
            self._dynamic_sliders["_anim_dropdown"] = anim_dropdown
            
            # Run Time Slider
            run_time_val = target_anim.kwargs.get("run_time", 1.0)
            rt_slider = PropertySlider(label="run_time", min_val=0.1, max_val=10.0, initial=float(run_time_val))
            rt_slider.value_changed.connect(
                lambda v, v_name=self._current_var_name: self._on_animation_kwarg_drag(v_name, "run_time", v)
            )
            rt_slider.value_released.connect(
                lambda v, v_name=self._current_var_name: self._on_animation_kwarg_release(v_name, "run_time", v)
            )
            anim_layout.addWidget(rt_slider)
            self._dynamic_sliders["_run_time"] = rt_slider
            
            self._content_layout.addWidget(anim_group)

    def _on_drag(self, target_var: str, prop_name: str, value: float) -> None:
        """Handle continuous slider drag — in-memory update only.

        Fast path: No SSD writes during drag.
        Just apply property directly to the mobject and re-render.

        Socket 5: File watcher is paused during drag.
        """
        # Pause file watcher to prevent feedback loop
        if self._file_watcher:
            self._file_watcher.pause()

        # Fast path: apply directly to scene mobject (in-memory)
        self._hot_swap.apply_single_property(target_var, prop_name, value)

        # Trigger re-render
        self._engine_state.request_render()

    def _on_release(self, target_var: str, prop_name: str, value: float) -> None:
        """Handle slider release — save to disk atomically.

        Slow path: AST surgery → atomic file save → resume watcher.
        This is the only time we touch the SSD.
        """
        # AST surgery: modify source code
        self._ast_mutator.update_property(target_var, prop_name, value)
        self._ast_mutator.save_atomic()

        # Resume file watcher
        if self._file_watcher:
            self._file_watcher.resume()

        logger.info(f"Slider released: {target_var}.{prop_name} = {value}")

    # -------------------------------------------------------------------------
    # Transform Callbacks
    # -------------------------------------------------------------------------
    def _on_transform_drag(self, target_var: str, method_name: str, value: float) -> None:
        """Fast path for transform (e.g. scale) updates during drag."""
        if self._file_watcher:
            self._file_watcher.pause()
        
        # We emit a signal so main.py can debounce and handle the full reload safely
        if hasattr(self, 'transform_drag_requested'):
            self.transform_drag_requested.emit(target_var, method_name, value)
        else:
            # Fallback if signal isn't wired up yet
            self._ast_mutator.update_transform_method(target_var, method_name, value)
            import os
            scene_file = self._ast_mutator._file_path
            if scene_file:
                self._ast_mutator.save_atomic()
                self._hot_swap.reload_from_file(scene_file)
            self._engine_state.request_render()

    def _on_transform_release(self, target_var: str, method_name: str, value: float) -> None:
        """Slow path for transform (e.g. scale) updates."""
        self._ast_mutator.update_transform_method(target_var, method_name, value)
        self._ast_mutator.save_atomic()
        if self._file_watcher:
            self._file_watcher.resume()
        logger.info(f"Transform released: {target_var}.{method_name}({value})")

    # -------------------------------------------------------------------------
    # Animation Callbacks
    # -------------------------------------------------------------------------
    def _on_animation_type_change(self, target_var: str, old_method: str, new_method: str) -> None:
        """Change animation effect directly in AST and save."""
        self._ast_mutator.update_animation_method(target_var, old_method, new_method)
        self._ast_mutator.save_atomic()
        logger.info(f"Animation effect changed: {old_method} -> {new_method} for {target_var}")

    def _on_animation_kwarg_drag(self, target_var: str, kwarg_name: str, value: float) -> None:
        """Fast path for animation kwarg (e.g. run_time). 
        Since this usually requires a full replay, we might not hot-swap it seamlessly, 
        but we can trigger a render or ignore it during fast drag.
        """
        pass # Ignore fast drag for animation timing to prevent stuttering

    def _on_animation_kwarg_release(self, target_var: str, kwarg_name: str, value: float) -> None:
        """Update animation kwarg in AST and save."""
        self._ast_mutator.update_animation_kwarg(target_var, kwarg_name, value)
        self._ast_mutator.save_atomic()
        logger.info(f"Animation kwarg released: {target_var} ({kwarg_name}={value})")

    def sync_from_code(self) -> None:
        """State Reconciliation: Update sliders from current AST values.

        Called after an external code edit to sync GUI with code.
        Blocks signals to prevent triggering the GUI→Code path.
        """
        if not self._current_var_name:
            return
            
        ref = self._ast_mutator.get_binding_by_name(self._current_var_name)
        if not ref:
            return

        ast_props = ref.properties
        schema_props = MANIM_SCHEMA.get(ref.constructor_name, DEFAULT_VMOBJECT_SCHEMA).copy()
        
        props = schema_props.copy()
        props.update(ast_props)

        for prop_name, widget in self._dynamic_sliders.items():
            if prop_name in props:
                val = props[prop_name]
                if isinstance(val, (int, float)) and isinstance(widget, PropertySlider):
                    widget.set_value(float(val))
                elif isinstance(val, str) and isinstance(widget, PropertyString):
                    widget.set_value(val)
                    
        if "_scale" in self._dynamic_sliders:
            scale_val = ref.transforms.get("scale", 1.0)
            self._dynamic_sliders["_scale"].set_value(float(scale_val))
            
        if "_rotate" in self._dynamic_sliders:
            rotate_val = ref.transforms.get("rotate", 0.0)
            self._dynamic_sliders["_rotate"].set_value(float(rotate_val))
            
        # Sync animation effects
        target_anim = None
        for anim in self._ast_mutator.animations:
            if anim.target_var == self._current_var_name:
                target_anim = anim
                break
                
        if target_anim:
            if "_anim_dropdown" in self._dynamic_sliders:
                # Keep case sensitivity for display if possible
                anim_effects = ["Create", "Write", "FadeIn", "FadeOut", "GrowFromCenter", "SpinInFromNothing", "DrawBorderThenFill"]
                current_effect = next((e for e in anim_effects if e.lower() == target_anim.method_name.lower()), target_anim.method_name)
                self._dynamic_sliders["_anim_dropdown"].set_value(current_effect)
                
            if "_run_time" in self._dynamic_sliders:
                run_time_val = target_anim.kwargs.get("run_time", 1.0)
                self._dynamic_sliders["_run_time"].set_value(float(run_time_val))

        logger.info("Dynamic sliders synced from code (State Reconciliation)")
