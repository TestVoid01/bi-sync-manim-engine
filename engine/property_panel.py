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


class PropertyTupleEditor(QWidget):
    """Interactive editor for numeric tuple/list values like x_range=[-2, 3, 1].

    Shows one numeric input per element, arranged horizontally.
    Emits the entire list on any element change.
    """

    value_changed = pyqtSignal(list)
    value_released = pyqtSignal(list)

    def __init__(
        self,
        label: str,
        initial: list[float],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._element_count = len(initial)
        self._inputs: list[QLineEdit] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        lbl = QLabel(label)
        lbl.setFixedWidth(92)
        lbl.setStyleSheet("color: #aaa; font-size: 12px;")
        row.addWidget(lbl)

        lbl_open = QLabel("[")
        lbl_open.setStyleSheet("color: #888; font-size: 13px; font-weight: bold;")
        lbl_open.setFixedWidth(8)
        row.addWidget(lbl_open)

        for idx, val in enumerate(initial):
            inp = QLineEdit(f"{float(val):.2f}")
            inp.setFixedWidth(70)
            inp.setAlignment(Qt.AlignmentFlag.AlignRight)
            inp.setStyleSheet("""
                QLineEdit {
                    background: #333;
                    color: #e5c07b;
                    border: 1px solid #555;
                    border-radius: 3px;
                    padding: 2px 4px;
                    font-family: monospace;
                    font-weight: bold;
                }
                QLineEdit:focus {
                    border-color: #e5c07b;
                }
            """)
            inp.textChanged.connect(self._on_element_changed)
            inp.editingFinished.connect(self._on_editing_finished)
            self._inputs.append(inp)
            row.addWidget(inp)

            if idx < len(initial) - 1:
                comma = QLabel(",")
                comma.setStyleSheet("color: #888; font-size: 13px;")
                comma.setFixedWidth(8)
                row.addWidget(comma)

        lbl_close = QLabel("]")
        lbl_close.setStyleSheet("color: #888; font-size: 13px; font-weight: bold;")
        lbl_close.setFixedWidth(8)
        row.addWidget(lbl_close)

        row.addStretch(1)
        outer.addLayout(row)

        # Status label for validation errors
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #e06c75; font-size: 10px; padding-left: 96px;")
        outer.addWidget(self._status_label)

    def _read_values(self) -> Optional[list[float]]:
        """Parse all element inputs. Returns None if any element is invalid."""
        values: list[float] = []
        for inp in self._inputs:
            text = inp.text().strip()
            try:
                values.append(float(text))
            except ValueError:
                return None
        return values

    def _on_element_changed(self) -> None:
        values = self._read_values()
        if values is not None:
            self._status_label.setText("")
            self.value_changed.emit(values)
        else:
            self._status_label.setText("⚠ invalid number")

    def _on_editing_finished(self) -> None:
        values = self._read_values()
        if values is not None:
            self._status_label.setText("")
            # Normalize display after editing
            for inp, val in zip(self._inputs, values):
                inp.blockSignals(True)
                inp.setText(f"{val:.2f}")
                inp.blockSignals(False)
            self.value_released.emit(values)
        else:
            self._status_label.setText("⚠ fix invalid values before committing")

    def set_value(self, values: list[float]) -> None:
        for inp, val in zip(self._inputs, values):
            inp.blockSignals(True)
            inp.setText(f"{float(val):.2f}")
            inp.blockSignals(False)


class PropertyCodeField(QWidget):
    """Editable text input for raw Python code expressions.

    Used for values like ``DOWN * 2``, ``axes.c2p(4, np.sin(4))``.
    Validates Python expression syntax on commit and wraps the result
    in a ``CodeExpression`` for the AST mutator.
    """

    value_changed = pyqtSignal(object)  # CodeExpression or raw str
    value_released = pyqtSignal(object)

    def __init__(
        self,
        label: str,
        initial: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        lbl = QLabel(label)
        lbl.setFixedWidth(92)
        lbl.setStyleSheet("color: #aaa; font-size: 12px;")
        row.addWidget(lbl)

        self._input = QLineEdit(str(initial))
        self._input.setStyleSheet("""
            QLineEdit {
                background: #2c313a;
                color: #98c379;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 3px 6px;
                font-family: 'Menlo', 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #98c379;
            }
        """)
        row.addWidget(self._input, stretch=1)

        outer.addLayout(row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #e06c75; font-size: 10px; padding-left: 96px;")
        outer.addWidget(self._status_label)

        # Only emit on commit (editing finished / Enter), not on every keystroke
        self._input.editingFinished.connect(self._on_editing_finished)

    def _validate_expression(self, code: str) -> Optional[str]:
        """Return None if expression is valid Python, else return error message."""
        code = code.strip()
        if not code:
            return "expression cannot be empty"
        try:
            import ast as ast_mod
            ast_mod.parse(code, mode="eval")
            return None
        except SyntaxError as exc:
            return f"syntax error: {exc.msg}"

    def _on_editing_finished(self) -> None:
        code = self._input.text().strip()
        error = self._validate_expression(code)
        if error is not None:
            self._status_label.setText(f"⚠ {error}")
            return

        self._status_label.setText("")
        from engine.ast_mutator import CodeExpression
        wrapped = CodeExpression(raw_code=code)
        self.value_released.emit(wrapped)

    def set_value(self, value: str) -> None:
        self._input.blockSignals(True)
        self._input.setText(str(value))
        self._input.blockSignals(False)
        self._status_label.setText("")


class PropertyPanel(QDockWidget):
    """Dock widget containing dynamic property sliders for scene manipulation.

    Phase 6.1: Dynamic Property Inspector
    Two-way sync:
        GUI → Code: Slider change → AST Mutator → file save
        Code → GUI: File change → parse → update sliders
    """

    transform_drag_requested = pyqtSignal(str, str, float)
    transform_release_requested = pyqtSignal()
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

        # Store dynamic widgets/specs keyed by stable PropertySpec key
        self._dynamic_sliders: dict[str, QWidget] = {}
        self._specs_by_key: dict[str, Any] = {}
        self._current_var_name: Optional[str] = None
        self._pending_commits: dict[tuple[str, str, str], tuple[str, str, Any]] = {}
        self._pending_widgets: dict[tuple[str, str, str], QWidget] = {}
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

    @staticmethod
    def _values_equivalent(left: Any, right: Any, *, tol: float = 1e-6) -> bool:
        if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
            return len(left) == len(right) and all(
                PropertyPanel._values_equivalent(a, b, tol=tol)
                for a, b in zip(left, right)
            )
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return abs(float(left) - float(right)) <= tol
        return left == right

    def _on_selection_changed(self, var_name: Optional[str]) -> None:
        """Triggered when user clicks an object in the canvas."""
        selection = getattr(self._engine_state, "selected_object", None)
        if selection is not None:
            self._current_var_name = selection.variable_name
        else:
            self._current_var_name = var_name
        self._build_dynamic_ui()

    def _build_dynamic_ui(self) -> None:
        """Rebuild the property panel from inspector-provided PropertySpec objects."""
        # Clear existing dynamic widgets
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self._dynamic_sliders.clear()
        self._specs_by_key.clear()

        selection = getattr(self._engine_state, "selected_object", None)

        from engine.property_inspector import PropertyInspector
        scene_getter = lambda: getattr(self._hot_swap, "_current_scene", None)
        inspector = PropertyInspector(
            ast_mutator=self._ast_mutator,
            object_registry=self._engine_state.object_registry,
            scene_getter=scene_getter,
        )
        specs = inspector.inspect_selection(selection) if selection else []

        if selection is None:
            self._title.setText("Scene Properties (No Selection)")
            return

        source_key = (
            getattr(selection, "nearest_editable_source_key", None)
            or getattr(selection, "source_key", None)
        )
        ref = (
            self._ast_mutator.get_binding_by_source_key(source_key)
            if source_key
            else self._ast_mutator.get_binding_by_name(selection.variable_name)
        )
        display_name = getattr(selection, "display_name", "") or getattr(
            selection,
            "variable_name",
            self._current_var_name or "Selection",
        )
        constructor_name = (
            ref.constructor_name
            if ref is not None
            else getattr(selection, "constructor_name", "Unknown")
        )
        self._title.setText(f"Properties: {display_name} ({constructor_name})")

        if selection is not None and getattr(selection, "editability", "source_editable") != "source_editable":
            self._engine_state.set_interaction_state("read_only_target")
            reason = getattr(selection, "read_only_reason", "") or "This runtime object is not source-editable."
            lbl = QLabel(reason)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #c0a060; font-size: 12px; padding: 6px 0;")
            self._content_layout.addWidget(lbl)

        if not specs:
            lbl = QLabel("No source-backed or live-readable properties found.")
            lbl.setStyleSheet("color: #888;")
            self._content_layout.addWidget(lbl)
            self._append_live_readout()
            return

        current_section = None
        for spec in specs:
            if spec.section != current_section:
                current_section = spec.section
                self._add_section_label(current_section)
            self._add_spec_widget(spec)

        self._add_section_label("Selection State")
        self._append_live_readout()

    def _add_spec_widget(self, spec: Any) -> None:
        self._specs_by_key[spec.key] = spec

        if spec.read_only:
            self._content_layout.addWidget(self._build_read_only_row(spec))
            return

        # ── Tuple editor (x_range, y_range, etc.) ──
        if spec.widget_hint == "tuple" and isinstance(spec.value, list):
            widget = PropertyTupleEditor(
                label=spec.display_key or spec.name,
                initial=[float(v) for v in spec.value],
            )
            widget.value_released.connect(
                lambda values, s=spec: self._handle_spec_release(s, values)
            )
            self._dynamic_sliders[spec.key] = widget
            self._content_layout.addWidget(widget)
            return

        # ── Code expression field (DOWN * 2, etc.) ──
        if spec.widget_hint == "code" and isinstance(spec.value, str):
            widget = PropertyCodeField(
                label=spec.display_key or spec.name,
                initial=spec.value,
            )
            widget.value_released.connect(
                lambda expr, s=spec: self._handle_spec_release(s, expr)
            )
            self._dynamic_sliders[spec.key] = widget
            self._content_layout.addWidget(widget)
            return

        if spec.widget_hint == "slider" and isinstance(spec.value, (int, float)):
            min_val, max_val, step = spec.range_hint or self._fallback_range_hint(spec.value)
            widget = PropertySlider(
                label=spec.display_key or spec.name,
                min_val=float(min_val),
                max_val=float(max_val),
                initial=float(spec.value),
                step=float(step),
            )
            widget.value_changed.connect(lambda value, s=spec: self._handle_spec_drag(s, value))
            widget.value_released.connect(lambda value, s=spec: self._handle_spec_release(s, value))
            self._dynamic_sliders[spec.key] = widget
            self._content_layout.addWidget(widget)
            return

        if spec.widget_hint == "checkbox":
            widget = PropertyDropdown(
                label=spec.display_key or spec.name,
                options=["False", "True"],
                initial="True" if bool(spec.value) else "False",
            )
            widget.value_changed.connect(
                lambda text, s=spec: self._handle_spec_release(s, text == "True")
            )
            self._dynamic_sliders[spec.key] = widget
            self._content_layout.addWidget(widget)
            return

        if spec.widget_hint == "color" and spec.options:
            widget = PropertyDropdown(
                label=spec.display_key or spec.name,
                options=list(spec.options),
                initial=str(spec.value),
            )
            widget.value_changed.connect(
                lambda text, s=spec: self._handle_spec_release(s, text)
            )
            self._dynamic_sliders[spec.key] = widget
            self._content_layout.addWidget(widget)
            return

        if spec.widget_hint == "text":
            widget = PropertyString(
                label=spec.display_key or spec.name,
                initial=str(spec.value),
            )
            if spec.apply_mode == "live_safe":
                widget.value_changed.connect(lambda text, s=spec: self._handle_spec_drag(s, text))
            widget.value_released.connect(lambda text, s=spec: self._handle_spec_release(s, text))
            self._dynamic_sliders[spec.key] = widget
            self._content_layout.addWidget(widget)
            return

        self._content_layout.addWidget(self._build_read_only_row(spec))

    def _build_read_only_row(self, spec: Any) -> QWidget:
        value_text = spec.value
        if isinstance(value_text, float):
            value_text = f"{value_text:.3f}"
        elif isinstance(value_text, list):
            value_text = str(value_text)
        elif not isinstance(value_text, str):
            value_text = str(value_text)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        name_lbl = QLabel(spec.display_key or spec.name)
        name_lbl.setStyleSheet("color: #ccc; font-size: 12px;")
        val_lbl = QLabel(value_text)
        val_lbl.setStyleSheet("color: #888; font-size: 12px;")
        row.addWidget(name_lbl)
        row.addStretch()
        row.addWidget(val_lbl)
        layout.addLayout(row)

        reason = spec.read_only_reason or (
            "reload-required value" if spec.apply_mode == "reload_only" else ""
        )
        if reason:
            reason_lbl = QLabel(reason)
            reason_lbl.setWordWrap(True)
            reason_lbl.setStyleSheet("color: #666; font-size: 10px; padding-left: 2px;")
            layout.addWidget(reason_lbl)

        return container

    @staticmethod
    def _fallback_range_hint(value: float) -> tuple[float, float, float]:
        numeric = float(value)
        if -1.0 <= numeric <= 1.0:
            return (-5.0, 5.0, 0.1)
        return (numeric - 10.0, numeric + 10.0, 0.1)

    def _handle_spec_drag(self, spec: Any, value: Any) -> None:
        if spec.read_only:
            return
        if spec.apply_mode == "preview_only":
            if self._file_watcher:
                self._file_watcher.pause()
            self._engine_state.set_interaction_state("previewing")
            target_var = self._current_var_name or ""
            prop_name = spec.param_name or spec.name
            self._hot_swap.apply_single_property(target_var, prop_name, value)
            self._engine_state.request_render()
            return
        if spec.apply_mode != "live_safe":
            self._queue_commit(spec, value, immediate=False)
            return

        if self._file_watcher:
            self._file_watcher.pause()
        self._engine_state.set_interaction_state("previewing")
        target_var = self._current_var_name or ""
        prop_name = spec.param_name or spec.name
        self._hot_swap.apply_single_property(target_var, prop_name, value)
        self._queue_commit(spec, value, immediate=False)
        self._engine_state.request_render()

    def _handle_spec_release(self, spec: Any, value: Any) -> None:
        if spec.read_only:
            return
        self._queue_commit(spec, value, immediate=True)

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
                if getattr(self._engine_state, 'is_external_reload_pending', False):
                    logger.warning("Property Panel transform save aborted: External file edit detected.")
                else:
                    self._ast_mutator.save_atomic()
                    self._hot_swap.reload_from_file(scene_file)
            self._engine_state.request_render()

    def _on_transform_release(self, target_var: str, method_name: str, value: float) -> None:
        """Slow path for transform (e.g. scale) updates."""
        if hasattr(self, 'transform_release_requested'):
            self.transform_release_requested.emit()

    # -------------------------------------------------------------------------
    # Animation Callbacks
    # -------------------------------------------------------------------------
    def _on_animation_type_change(self, target_var: str, old_method: str, new_method: str) -> None:
        """Change animation effect directly in AST and save."""
        if getattr(self._engine_state, 'is_external_reload_pending', False):
            logger.warning("Animation type save aborted: External file edit detected.")
            return

        if self._file_watcher:
            self._file_watcher.pause()

        self._ast_mutator.update_animation_method(target_var, old_method, new_method)

        if self._file_watcher:
            self._ast_mutator.save_atomic()
            self._file_watcher.notify_internal_commit()
            self._file_watcher.resume()

        logger.info(f"Animation effect changed: {old_method} -> {new_method} for {target_var}")

    def _on_animation_kwarg_drag(self, target_var: str, kwarg_name: str, value: float) -> None:
        """Fast path for animation kwarg (e.g. run_time). 
        Since this usually requires a full replay, we might not hot-swap it seamlessly, 
        but we can trigger a render or ignore it during fast drag.
        """
        pass # Ignore fast drag for animation timing to prevent stuttering

    def _on_animation_kwarg_release(self, target_var: str, kwarg_name: str, value: float) -> None:
        """Update animation kwarg in AST and save."""
        if getattr(self._engine_state, 'is_external_reload_pending', False):
            logger.warning("Animation kwarg save aborted: External file edit detected.")
            return

        if self._file_watcher:
            self._file_watcher.pause()

        self._ast_mutator.update_animation_kwarg(target_var, kwarg_name, value)

        if self._file_watcher:
            self._ast_mutator.save_atomic()
            self._file_watcher.notify_internal_commit()
            self._file_watcher.resume()

        logger.info(f"Animation kwarg released: {target_var} ({kwarg_name}={value})")
    def sync_from_code(self) -> None:
        """Rebuild from source-of-truth after file or AST changes."""
        self._build_dynamic_ui()
        logger.info("Dynamic property panel rebuilt from code")

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
            source_key=getattr(selection, "nearest_editable_source_key", None) or selection.source_key,
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
        spec: Any,
        value: Any,
        *,
        immediate: bool = False,
    ) -> None:
        key = ("spec", self._current_var_name or "", spec.key)
        self._pending_commits[key] = (spec, value)
        widget = self._dynamic_sliders.get(spec.key)
        if hasattr(widget, "set_pending"):
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
        for _key, payload in commits:
            spec, value = payload
            if self._commit_property(spec, value):
                changed = True

        if changed:
            if getattr(self._engine_state, 'is_external_reload_pending', False):
                logger.warning("Property panel commit aborted: External file edit detected.")
            else:
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

    def _commit_property(self, spec: Any, value: Any) -> bool:
        target_var = self._current_var_name or ""
        prop_name = spec.param_name or spec.name
        selection = getattr(self._engine_state, "selected_object", None)
        strategy = self._ast_mutator.plan_property_persistence(
            target_var,
            prop_name,
            source_key=getattr(selection, "nearest_editable_source_key", None) or getattr(selection, "source_key", None),
            path=tuple(getattr(selection, "path", ()) or ()),
        )
        if strategy.no_persist:
            logger.info(f"Skipped persist for {target_var}.{prop_name}: {strategy.reason}")
            self._engine_state.record_preview_drift(
                f"{target_var}.{prop_name}: {strategy.reason}"
            )
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
            source_key=getattr(selection, "nearest_editable_source_key", None) or getattr(selection, "source_key", None),
            path=tuple(getattr(selection, "path", ()) or ()),
        )
        if strategy.no_persist:
            logger.info(f"Skipped transform persist for {target_var}.{method_name}: {strategy.reason}")
            self._engine_state.record_preview_drift(
                f"{target_var}.{method_name} transform: {strategy.reason}"
            )
            return False
        self._ast_mutator.update_transform_method(target_var, method_name, value)
        logger.info(f"Transform committed: {target_var}.{method_name}({value})")
        return True
