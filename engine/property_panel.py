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

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QDockWidget,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QPushButton,
    QComboBox,
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
    "Text": {
        "color": "WHITE",
        "font_size": 48.0,
        "fill_opacity": 1.0,
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
        self._step_options = [0.01, 0.1, 1.0]
        if step not in self._step_options:
            self._step_options.append(step)
            self._step_options = sorted(set(self._step_options))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        # Label
        self._label = QLabel(label)
        self._label.setFixedWidth(92)
        self._label.setStyleSheet("color: #aaa; font-size: 12px;")
        row.addWidget(self._label)

        # Minus button
        self._btn_minus = QPushButton("-")
        self._btn_minus.setFixedWidth(26)
        row.addWidget(self._btn_minus)

        # Numeric input
        self._value_input = QLineEdit(f"{initial:.2f}")
        self._value_input.setFixedWidth(70)
        self._value_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._value_input.setStyleSheet("""
            QLineEdit {
                background: #333;
                color: #4a90d9;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 2px 4px;
                font-weight: bold;
            }
        """)
        self._value_input.installEventFilter(self)
        row.addWidget(self._value_input)

        # Plus button
        self._btn_plus = QPushButton("+")
        self._btn_plus.setFixedWidth(26)
        row.addWidget(self._btn_plus)

        # Step selector
        self._step_combo = QComboBox()
        self._step_combo.setFixedWidth(72)
        self._step_combo.addItems([f"{s:g}" for s in self._step_options])
        self._step_combo.setCurrentText(f"{self._step:g}")
        row.addWidget(self._step_combo)
        row.addStretch(1)
        layout.addLayout(row)

        # Optional coarse slider
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
        layout.addWidget(self._slider)
        self._pending_label = QLabel("")
        self._pending_label.setStyleSheet("color: #d1b36a; font-size: 10px;")
        layout.addWidget(self._pending_label)

        # Connect signals
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._btn_minus.clicked.connect(lambda: self._nudge(-1))
        self._btn_plus.clicked.connect(lambda: self._nudge(1))
        self._value_input.editingFinished.connect(self._on_input_committed)
        self._step_combo.currentTextChanged.connect(self._on_step_changed)

    def eventFilter(self, obj, event):
        if obj is self._value_input and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Down):
                self._nudge(-1, modifiers=event.modifiers())
                return True
            if key in (Qt.Key.Key_Right, Qt.Key.Key_Up):
                self._nudge(1, modifiers=event.modifiers())
                return True
        return super().eventFilter(obj, event)

    def _on_slider_changed(self, int_value: int) -> None:
        """Continuous update during drag."""
        value = int_value / self._multiplier
        self._value_input.setText(f"{value:.2f}")
        self.value_changed.emit(value)

    def _on_slider_released(self) -> None:
        """Final update on mouse release."""
        value = self._slider.value() / self._multiplier
        self.value_released.emit(value)

    def _on_input_committed(self) -> None:
        try:
            value = float(self._value_input.text().strip())
        except ValueError:
            value = self.get_value()
        value = max(self._min, min(self._max, value))
        self._slider.blockSignals(True)
        self._slider.setValue(int(value * self._multiplier))
        self._slider.blockSignals(False)
        self._value_input.setText(f"{value:.2f}")
        self.value_changed.emit(value)
        self.value_released.emit(value)

    def _on_step_changed(self, text: str) -> None:
        try:
            self._step = float(text)
        except ValueError:
            self._step = 0.1

    def _nudge(self, direction: int, modifiers=None) -> None:
        step = self._step
        if modifiers is not None:
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                step *= 10.0
            if modifiers & Qt.KeyboardModifier.AltModifier:
                step *= 0.1
        value = self.get_value() + (direction * step)
        value = max(self._min, min(self._max, value))
        self._slider.blockSignals(True)
        self._slider.setValue(int(value * self._multiplier))
        self._slider.blockSignals(False)
        self._value_input.setText(f"{value:.2f}")
        self.value_changed.emit(value)

    def set_pending(self, pending: bool) -> None:
        self._pending_label.setText("pending..." if pending else "")

    def set_value(self, value: float) -> None:
        """Programmatically set the slider value (for state reconciliation).

        Blocks signals to prevent feedback loop.
        """
        self._slider.blockSignals(True)
        self._slider.setValue(int(value * self._multiplier))
        self._value_input.setText(f"{value:.2f}")
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

    transform_drag_requested = pyqtSignal(str, str, float)
    full_reload_requested = pyqtSignal(str)

    def __init__(
        self,
        engine_state: EngineState,
        ast_mutator: ASTMutator,        hot_swap: HotSwapInjector,
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
        self._pending_commits: dict[tuple[str, str, str], tuple[str, str, Any]] = {}
        self._pending_widgets: dict[tuple[str, str, str], PropertySlider] = {}
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(150)
        self._commit_timer.timeout.connect(self._flush_pending_commits)
        self._engine_state.set_interaction_state("idle")

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
        selection = getattr(self._engine_state, "selected_object", None)
        if selection is not None:
            self._current_var_name = selection.variable_name
        else:
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

        selection = getattr(self._engine_state, "selected_object", None)

        from engine.property_inspector import PropertyInspector
        scene_getter = lambda: getattr(self._hot_swap, "_current_scene", None)
        inspector = PropertyInspector(
            ast_mutator=self._ast_mutator,
            object_registry=self._engine_state.object_registry,
            scene_getter=scene_getter,
        )
        live_specs = inspector.inspect_selection(selection) if selection else []

        if selection is not None and getattr(selection, "editability", "source_editable") != "source_editable":
            self._engine_state.set_interaction_state("read_only_target")
            self._title.setText(f"Properties: {selection.display_name or 'Selection'} (Read-only)")
            reason = getattr(selection, "read_only_reason", "") or "This runtime object is not source-editable."
            lbl = QLabel(reason)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #c0a060; font-size: 12px; padding: 6px 0;")
            self._content_layout.addWidget(lbl)
            
            if live_specs:
                self._add_section_label("Discovered Properties")
                for spec in live_specs:
                    if spec.section == "Live Readout":
                        val_str = str(spec.value)
                        if isinstance(spec.value, float):
                            val_str = f"{spec.value:.3f}"
                        row = QHBoxLayout()
                        row.setContentsMargins(0, 0, 0, 0)
                        name_lbl = QLabel(spec.name)
                        name_lbl.setStyleSheet("color: #ccc; font-size: 12px;")
                        val_lbl = QLabel(val_str)
                        val_lbl.setStyleSheet("color: #888; font-size: 12px;")
                        row.addWidget(name_lbl)
                        row.addStretch()
                        row.addWidget(val_lbl)
                        w = QWidget()
                        w.setLayout(row)
                        self._content_layout.addWidget(w)
            
            self._append_live_readout()
            return

        if not self._current_var_name:
            self._title.setText("Scene Properties (No Selection)")
            return

        # Fetch AST properties for this variable
        ref = self._ast_mutator.get_binding_by_name(self._current_var_name)
        if not ref:
            self._title.setText(f"Scene Properties (Unknown: {self._current_var_name})")
            return

        self._title.setText(f"Properties: {self._current_var_name} ({ref.constructor_name})")
        self._add_section_label("Source Properties")

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
        self._add_section_label("Source Chain")
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

        if live_specs:
            self._add_section_label("Discovered Properties")
            for spec in live_specs:
                if spec.section == "Live Readout" and spec.name not in props:
                    if spec.widget_hint == "slider" and isinstance(spec.value, (int, float)):
                        min_val, max_val, _ = spec.range_hint or (0.0, 1.0, 0.1)
                        if spec.value < min_val: min_val = float(spec.value) - 5.0
                        if spec.value > max_val: max_val = float(spec.value) + 5.0
                        if min_val == max_val: max_val += 1.0
                        slider = PropertySlider(
                            label=spec.name,
                            min_val=min_val,
                            max_val=max_val,
                            initial=float(spec.value)
                        )
                        slider.value_changed.connect(
                            lambda v, v_name=self._current_var_name, p_name=spec.name: 
                                self._on_drag(v_name, p_name, v)
                        )
                        slider.value_released.connect(
                            lambda v, v_name=self._current_var_name, p_name=spec.name: 
                                self._on_release(v_name, p_name, v)
                        )
                        self._content_layout.addWidget(slider)
                        self._dynamic_sliders[spec.name] = slider
                    else:
                        val_str = str(spec.value)
                        if isinstance(spec.value, float):
                            val_str = f"{spec.value:.3f}"
                        row = QHBoxLayout()
                        row.setContentsMargins(0, 0, 0, 0)
                        name_lbl = QLabel(spec.name)
                        name_lbl.setStyleSheet("color: #ccc; font-size: 12px;")
                        val_lbl = QLabel(val_str)
                        val_lbl.setStyleSheet("color: #888; font-size: 12px;")
                        row.addWidget(name_lbl)
                        row.addStretch()
                        row.addWidget(val_lbl)
                        w = QWidget()
                        w.setLayout(row)
                        self._content_layout.addWidget(w)

        self._add_section_label("Live Readout")
        self._append_live_readout()

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
        self._engine_state.set_interaction_state("previewing")
        self._hot_swap.apply_single_property(target_var, prop_name, value)
        self._queue_commit(target_var, prop_name, value, kind="property")

        # Trigger re-render
        self._engine_state.request_render()

    def _on_release(self, target_var: str, prop_name: str, value: float) -> None:
        """Handle slider release — save to disk atomically.

        Slow path: AST surgery → atomic file save → resume watcher.
        This is the only time we touch the SSD.
        """
        self._queue_commit(target_var, prop_name, value, kind="property", immediate=True)

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
            self._queue_commit(target_var, method_name, value, kind="transform")
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
        self._queue_commit(target_var, method_name, value, kind="transform", immediate=True)

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

    def commit_pending_edits(self) -> None:
        """Compatibility hook used before export.

        This panel applies edits immediately on slider/string release, so there
        is no deferred transaction queue to flush.
        """
        self._flush_pending_commits()
        if self._file_watcher:
            self._file_watcher.resume()

    def _add_section_label(self, text: str) -> None:
        label = QLabel(text)
        label.setStyleSheet("color: #8fb3ff; font-size: 11px; font-weight: bold; padding: 6px 0 2px 0;")
        self._content_layout.addWidget(label)

    def _append_live_readout(self) -> None:
        selection = getattr(self._engine_state, "selected_object", None)
        if selection is None:
            lbl = QLabel("No live object selected.")
            lbl.setStyleSheet("color: #888; font-size: 12px;")
            self._content_layout.addWidget(lbl)
            return

        scene = getattr(self._hot_swap, "_current_scene", None)
        registry = getattr(self._engine_state, "object_registry", None)
        live_mob = None
        if scene is not None and registry is not None:
            try:
                live_mob = registry.find_mobject(scene, selection.mobject_id)
            except Exception:
                live_mob = None

        rows: list[tuple[str, str]] = [
            ("display", selection.display_name or selection.variable_name),
            ("source", selection.source_key or "runtime-only"),
            ("mode", selection.editability),
        ]
        strategy = self._ast_mutator.plan_property_persistence(
            selection.variable_name,
            "__selection__",
            source_key=selection.source_key,
            path=tuple(selection.path or ()),
        )
        rows.append(("persist", strategy.mode))
        if strategy.reason:
            rows.append(("persist_reason", strategy.reason))

        if live_mob is not None:
            try:
                center = live_mob.get_center()
                rows.append(("center", f"({float(center[0]):.2f}, {float(center[1]):.2f})"))
            except Exception:
                pass
            try:
                rows.append(("width", f"{float(getattr(live_mob, 'width', 0.0)):.2f}"))
                rows.append(("height", f"{float(getattr(live_mob, 'height', 0.0)):.2f}"))
            except Exception:
                pass
            try:
                color = getattr(live_mob, "color", None)
                if color is not None:
                    rows.append(("color", str(color)))
            except Exception:
                pass

        for key, value in rows:
            lbl = QLabel(f"{key}: {value}")
            lbl.setStyleSheet("color: #bbb; font-size: 11px; padding: 1px 0;")
            self._content_layout.addWidget(lbl)

    def _queue_commit(
        self,
        target_var: str,
        prop_name: str,
        value: Any,
        *,
        kind: str,
        immediate: bool = False,
    ) -> None:
        key = (kind, target_var, prop_name)
        self._pending_commits[key] = (target_var, prop_name, value)
        widget = self._dynamic_sliders.get(prop_name)
        if isinstance(widget, PropertySlider):
            widget.set_pending(True)
            self._pending_widgets[key] = widget
        self._engine_state.interaction_burst_active = True
        self._engine_state.set_interaction_state(self._engine_state.STATE_COMMIT_PENDING)
        self._engine_state.reload_guard_mode = self._engine_state.RELOAD_BLOCK_DURING_BURST
        if immediate:
            self._flush_pending_commits()
            return
        self._commit_timer.start()

    def _flush_pending_commits(self) -> None:
        if not self._pending_commits:
            self._engine_state.interaction_burst_active = False
            self._engine_state.set_interaction_state(self._engine_state.STATE_IDLE)
            self._engine_state.reload_guard_mode = self._engine_state.RELOAD_ALLOW_FULL
            return

        commits = list(self._pending_commits.items())
        self._pending_commits.clear()
        self._engine_state.set_interaction_state(self._engine_state.STATE_COMMITTING)

        changed = False
        for (kind, _target_var, _prop_name), (target_var, prop_name, value) in commits:
            if kind == "property":
                if self._commit_property(target_var, prop_name, value): changed = True
            elif kind == "transform":
                if self._commit_transform(target_var, prop_name, value): changed = True

        if changed:
            self._ast_mutator.save_atomic()
            if self._file_watcher:
                self._file_watcher.notify_internal_commit()

        for key, widget in list(self._pending_widgets.items()):
            if isinstance(widget, PropertySlider):
                widget.set_pending(False)
            self._pending_widgets.pop(key, None)

        if self._file_watcher:
            self._file_watcher.resume()
        self._engine_state.interaction_burst_active = False
        self._engine_state.set_interaction_state(self._engine_state.STATE_SETTLED)
        self._engine_state.reload_guard_mode = self._engine_state.RELOAD_ALLOW_FULL

    def _commit_property(self, target_var: str, prop_name: str, value: Any) -> bool:
        selection = getattr(self._engine_state, "selected_object", None)
        strategy = self._ast_mutator.plan_property_persistence(
            target_var,
            prop_name,
            source_key=getattr(selection, "source_key", None),
            path=tuple(getattr(selection, "path", ()) or ()),
        )
        if strategy.no_persist:
            logger.info(f"Skipped persist for {target_var}.{prop_name}: {strategy.reason}")
            return False
        if not self._ast_mutator.persist_property_edit(target_var, prop_name, value, strategy):
            logger.warning(f"Persist failed for {target_var}.{prop_name}: {strategy.reason}")
            return False
        logger.info(f"Slider committed: {target_var}.{prop_name} = {value}")
        return True

    def _commit_transform(self, target_var: str, method_name: str, value: float) -> bool:
        selection = getattr(self._engine_state, "selected_object", None)
        strategy = self._ast_mutator.plan_property_persistence(
            target_var,
            method_name,
            source_key=getattr(selection, "source_key", None),
            path=tuple(getattr(selection, "path", ()) or ()),
        )
        if strategy.no_persist:
            logger.info(f"Skipped transform persist for {target_var}.{method_name}: {strategy.reason}")
            return False
        self._ast_mutator.update_transform_method(target_var, method_name, value)
        logger.info(f"Transform committed: {target_var}.{method_name}({value})")
        return True
