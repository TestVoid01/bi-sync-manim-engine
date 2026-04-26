"""
Bi-Sync Code Editor Panel — Live Two-Way Code Editor
======================================================

A QPlainTextEdit wrapped in a QDockWidget that shows the current
scene's Python source code. Provides the "ghost-typing" experience:

    Code → Graphics: User types code → 500ms debounce → file save → hot-swap
    Graphics → Code: Shape dragged → AST save → file watcher → editor reloads

Key Design:
    - 500ms typing debounce prevents saves on every keystroke
    - blockSignals() during sync_from_file() prevents save-loop
    - Monospaced dark theme matching the Manim aesthetic
    - Line numbers for code navigation
    - _is_programmatic_change flag prevents feedback loops
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QSyntaxHighlighter
from PyQt6.QtWidgets import (
    QDockWidget,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
    QLabel,
)

logger = logging.getLogger("bisync.code_editor")

if TYPE_CHECKING:
    from engine.state import EngineState
    from engine.file_watcher import SceneFileWatcher

@dataclass
class ShadowBuildResult:
    applied: bool
    status: str
    error: Optional[str] = None
    applied_source: Optional[str] = None

class PythonHighlighter(QSyntaxHighlighter):
    """Minimal Python syntax highlighter for the code editor.

    Highlights keywords, strings, comments, and numbers
    with colors matching the dark theme.
    """

    KEYWORDS = [
        "import", "from", "class", "def", "return", "self",
        "if", "else", "elif", "for", "while", "in", "not",
        "and", "or", "True", "False", "None", "pass", "break",
        "continue", "try", "except", "finally", "with", "as",
        "yield", "lambda", "raise", "global", "nonlocal",
    ]

    BUILTINS = [
        "print", "range", "len", "int", "float", "str", "list",
        "dict", "tuple", "set", "type", "super", "isinstance",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []

        # Keywords — purple/magenta
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#c678dd"))
        kw_fmt.setFontWeight(QFont.Weight.Bold)
        for kw in self.KEYWORDS:
            import re
            self._rules.append((re.compile(rf"\b{kw}\b"), kw_fmt))

        # Builtins — cyan
        builtin_fmt = QTextCharFormat()
        builtin_fmt.setForeground(QColor("#56b6c2"))
        for b in self.BUILTINS:
            import re
            self._rules.append((re.compile(rf"\b{b}\b"), builtin_fmt))

        # Numbers — orange
        self._num_fmt = QTextCharFormat()
        self._num_fmt.setForeground(QColor("#d19a66"))
        import re
        self._rules.append((re.compile(r"\b\d+\.?\d*\b"), self._num_fmt))

        # Strings — green
        self._str_fmt = QTextCharFormat()
        self._str_fmt.setForeground(QColor("#98c379"))
        self._rules.append((re.compile(r'\".*?\"'), self._str_fmt))
        self._rules.append((re.compile(r"\'.*?\'"), self._str_fmt))

        # Comments — gray
        self._comment_fmt = QTextCharFormat()
        self._comment_fmt.setForeground(QColor("#5c6370"))
        self._comment_fmt.setFontItalic(True)
        self._rules.append((re.compile(r"#.*$"), self._comment_fmt))

        # Class/function names — yellow
        self._class_fmt = QTextCharFormat()
        self._class_fmt.setForeground(QColor("#e5c07b"))
        self._class_fmt.setFontWeight(QFont.Weight.Bold)
        self._rules.append((re.compile(r"\bclass\s+(\w+)"), self._class_fmt))
        self._rules.append((re.compile(r"\bdef\s+(\w+)"), self._class_fmt))

        # Manim constants — red
        manim_fmt = QTextCharFormat()
        manim_fmt.setForeground(QColor("#e06c75"))
        manim_consts = [
            "BLUE", "RED", "GREEN", "YELLOW", "WHITE", "ORANGE",
            "ORIGIN", "LEFT", "RIGHT", "UP", "DOWN",
            "Circle", "Square", "Triangle", "Dot", "Line",
            "Scene", "Rectangle",
        ]
        for mc in manim_consts:
            self._rules.append((re.compile(rf"\b{mc}\b"), manim_fmt))

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                start = match.start()
                length = match.end() - start
                self.setFormat(start, length, fmt)


class CodeEditorPanel(QDockWidget):
    """Dock widget containing a live Python code editor.

    Two-way sync:
        1. User types → 500ms debounce → save to disk → hot-swap → canvas update
        2. Shape dragged → AST save → file watcher → sync_from_file() → editor updates
    """

    def __init__(
        self,
        scene_file: str,
        engine_state: EngineState,
        file_watcher: Optional[SceneFileWatcher] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__("Code Editor", parent)

        self._scene_file = scene_file
        self._engine_state = engine_state
        self._file_watcher = file_watcher

        # Callback: MainWindow sets this to trigger full reload pipeline
        # (re-parse AST → hot-swap scene → sync sliders)
        self._on_code_saved_callback = None

        # Flag to prevent feedback loop:
        # True when we're programmatically updating text (sync_from_file)
        self._is_programmatic_change: bool = False

        # Don't allow closing
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        # Container
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QLabel(f"  {os.path.basename(scene_file)}")
        header.setStyleSheet(
            "background: #21252b; color: #abb2bf; font-size: 12px; "
            "padding: 6px 8px; border-bottom: 1px solid #181a1f;"
        )
        layout.addWidget(header)

        # Code editor
        self._editor = QPlainTextEdit()
        self._editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #282c34;
                color: #abb2bf;
                border: none;
                selection-background-color: #3e4451;
                selection-color: #abb2bf;
            }
        """)

        # Monospaced font
        font = QFont("JetBrains Mono", 13)
        if not font.exactMatch():
            font = QFont("Menlo", 13)
            if not font.exactMatch():
                font = QFont("Monaco", 13)
                if not font.exactMatch():
                    font = QFont("Courier New", 13)
        font.setFixedPitch(True)
        self._editor.setFont(font)

        # Tab width
        self._editor.setTabStopDistance(
            self._editor.fontMetrics().horizontalAdvance(" ") * 4
        )

        # Line wrap off for code
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        # Syntax highlighting
        self._highlighter = PythonHighlighter(self._editor.document())

        layout.addWidget(self._editor)
        self.setWidget(container)
        self.setMinimumWidth(350)

        # Load initial content
        self._load_file()

        # 500ms typing debounce timer
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._on_debounce_save)

        # Connect text changes to debounce
        self._editor.textChanged.connect(self._on_text_changed)

        logger.info("CodeEditorPanel created")

    def _load_file(self) -> None:
        """Load the scene file content into the editor."""
        try:
            content = Path(self._scene_file).read_text(encoding="utf-8")
            self._is_programmatic_change = True
            self._editor.setPlainText(content)
            self._is_programmatic_change = False
            pass
        except Exception as e:
            logger.error(f"Failed to load file: {e}")

    def _on_text_changed(self) -> None:
        """Called on every keystroke. Starts the 500ms debounce timer.

        If _is_programmatic_change is True, we skip saving
        (prevents feedback loop when sync_from_file updates text).
        """
        if self._is_programmatic_change:
            return
        # Restart the debounce timer
        self._save_timer.start()

    def set_on_code_saved(self, callback) -> None:
        """Set the callback for when user types and code is saved.

        MainWindow sets this to trigger: re-parse AST → hot-swap → sync sliders.
        """
        self._on_code_saved_callback = callback

    def _on_debounce_save(self) -> None:
        """Called 500ms after the user stops typing. Saves to disk + reloads scene.

        Flow:
            1. Pause file watcher (prevent detecting our own save)
            2. Write editor content to disk
            3. Call MainWindow's reload pipeline (AST + hot-swap + sliders)
            4. Resume file watcher after delay
        """
        # Pause file watcher to prevent feedback
        if self._file_watcher:
            self._file_watcher.pause()

        try:
            content = self._editor.toPlainText()

            # Validate Python syntax before saving
            import ast as ast_mod
            try:
                ast_mod.parse(content)
            except SyntaxError as e:
                logger.warning(f"Syntax error in editor, skipping save: {e}")
                if self._file_watcher:
                    self._file_watcher.resume()
                return

            if self._on_code_saved_callback:
                result = self._on_code_saved_callback(content)
                if result and not getattr(result, "applied", True):
                    logger.warning(f"Shadow build rejected: {getattr(result, 'status', 'unknown')}")
                else:
                    logger.info("Code Editor → shadow build accepted & saved")
            else:
                # Fallback: write to file and at least repaint
                Path(self._scene_file).write_text(content, encoding="utf-8")
                self._engine_state.request_render()

        except Exception as e:
            logger.error(f"Code Editor save failed: {e}")
        finally:
            # Resume file watcher after a short delay
            QTimer.singleShot(400, self._resume_watcher)

    def _resume_watcher(self) -> None:
        """Resume file watcher after save."""
        if self._file_watcher:
            self._file_watcher.resume()

    def sync_from_file(self) -> None:
        """Reload editor content from disk (State Reconciliation).

        Called when AST Mutator saves the file after a drag or slider change.
        The "ghost-typing" effect: code updates itself visually.

        Uses _is_programmatic_change flag to prevent triggering
        another save (which would create an infinite loop).
        """
        try:
            content = Path(self._scene_file).read_text(encoding="utf-8")
            current = self._editor.toPlainText()

            # Only update if content actually changed
            if content != current:
                # Save cursor position
                cursor = self._editor.textCursor()
                pos = cursor.position()
                scroll_val = self._editor.verticalScrollBar().value()

                # Update text without triggering save
                self._is_programmatic_change = True
                self._editor.setPlainText(content)
                self._is_programmatic_change = False

                # Restore cursor position (best effort)
                cursor = self._editor.textCursor()
                pos = min(pos, len(content))
                cursor.setPosition(pos)
                self._editor.setTextCursor(cursor)
                self._editor.verticalScrollBar().setValue(scroll_val)

                pass

        except Exception as e:
            logger.error(f"Code Editor sync failed: {e}")

    def flush_pending_save(self) -> Optional[str]:
        """Force-apply pending debounce save before export.

        Returns:
            None on success, otherwise an error string.
        """
        try:
            if self._save_timer.isActive():
                self._save_timer.stop()
                self._on_debounce_save()
            return None
        except Exception as e:
            logger.error(f"Code Editor flush failed: {e}")
            return str(e)
