"""
Bi-Sync Export Dialog & Worker — Video Export System
=====================================================

Settings dialog for video export configuration and a QThread-based
background worker that runs Manim's CLI renderer.

Components:
    ExportDialog  — Modal QDialog with resolution/fps/format pickers
    ExportWorker  — QThread that runs `manim render` in background
    ExportProgress — Progress overlay with ETA and cancel support

Safety:
    - Rendering runs in QThread (UI never freezes)
    - Uses Manim's Cairo renderer for export (not our hijacked OpenGL)
    - Cancel button sends SIGTERM to subprocess
    - Temp files cleaned up automatically by Manim
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QComboBox,
    QPushButton,
    QLabel,
    QProgressBar,
    QFileDialog,
    QLineEdit,
    QGroupBox,
    QMessageBox,
    QWidget,
)

logger = logging.getLogger("bisync.export")

# ── Resolution Presets ──
RESOLUTIONS = {
    "720p (HD)": (1280, 720),
    "1080p (Full HD)": (1920, 1080),
    "2K (QHD)": (2560, 1440),
    "4K (UHD)": (3840, 2160),
}

FPS_OPTIONS = [24, 30, 60, 120]

FORMAT_OPTIONS = {
    "MP4 (H.264)": "mp4",
    "GIF": "gif",
    "WebM (VP9)": "webm",
}


def build_export_command(settings: dict) -> list[str]:
    return [
        "manim", "render",
        settings["scene_file"],
        settings["scene_name"],
        "--renderer", "cairo",
        "--format", settings["format"],
        "--fps", str(settings["fps"]),
        "-r", f"{settings['width']},{settings['height']}",
        "--output_file", os.path.basename(settings["output_path"]),
        "--media_dir", os.path.dirname(settings["output_path"]),
    ]


class ExportDialog(QDialog):
    """Modal dialog for configuring video export settings."""

    def __init__(self, scene_file: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Export Animation")
        self.setFixedSize(480, 400)
        self._scene_file = scene_file

        # Dark theme
        self.setStyleSheet("""
            QDialog {
                background: #282c34;
                color: #abb2bf;
            }
            QGroupBox {
                border: 1px solid #3a3f4b;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: bold;
                color: #61afef;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLabel {
                color: #abb2bf;
                font-size: 13px;
            }
            QComboBox, QLineEdit {
                background: #21252b;
                color: #abb2bf;
                border: 1px solid #3a3f4b;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 13px;
                min-height: 28px;
            }
            QComboBox:hover, QLineEdit:hover {
                border-color: #61afef;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QPushButton {
                background: #3a3f4b;
                color: #abb2bf;
                border: 1px solid #4b5263;
                border-radius: 4px;
                padding: 8px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #4b5263;
                border-color: #61afef;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Title ──
        title = QLabel("🎬  Export Animation Video")
        title.setFont(QFont("", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #61afef; padding: 4px 0;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # ── Quality Settings ──
        quality_group = QGroupBox("Quality Settings")
        quality_layout = QFormLayout(quality_group)
        quality_layout.setSpacing(10)

        self._res_combo = QComboBox()
        for name in RESOLUTIONS:
            self._res_combo.addItem(name)
        self._res_combo.setCurrentIndex(1)  # Default: 1080p
        quality_layout.addRow("Resolution:", self._res_combo)

        self._fps_combo = QComboBox()
        for fps in FPS_OPTIONS:
            self._fps_combo.addItem(f"{fps} fps", fps)
        self._fps_combo.setCurrentIndex(1)  # Default: 30fps
        quality_layout.addRow("Frame Rate:", self._fps_combo)

        self._fmt_combo = QComboBox()
        for name in FORMAT_OPTIONS:
            self._fmt_combo.addItem(name)
        quality_layout.addRow("Format:", self._fmt_combo)

        layout.addWidget(quality_group)

        # ── Output Path ──
        output_group = QGroupBox("Output")
        output_layout = QHBoxLayout(output_group)

        self._output_path = QLineEdit()
        default_output = str(
            Path(scene_file).parent.parent / "exports" / "animation.mp4"
        )
        self._output_path.setText(default_output)
        output_layout.addWidget(self._output_path)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse)
        browse_btn.setFixedWidth(90)
        output_layout.addWidget(browse_btn)

        layout.addWidget(output_group)

        # ── Estimate Label ──
        self._estimate_label = QLabel("")
        self._estimate_label.setStyleSheet(
            "color: #5c6370; font-size: 12px; padding: 4px 0;"
        )
        self._estimate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._estimate_label)
        self._update_estimate()
        self._res_combo.currentIndexChanged.connect(self._update_estimate)
        self._fps_combo.currentIndexChanged.connect(self._update_estimate)

        # ── Buttons ──
        btn_layout = QHBoxLayout()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        btn_layout.addStretch()

        self._export_btn = QPushButton("🚀  Start Export")
        self._export_btn.setStyleSheet("""
            QPushButton {
                background: #61afef;
                color: #282c34;
                font-weight: bold;
                padding: 10px 28px;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #78bef2;
            }
        """)
        self._export_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._export_btn)

        layout.addLayout(btn_layout)

    def _on_browse(self) -> None:
        fmt_ext = list(FORMAT_OPTIONS.values())[self._fmt_combo.currentIndex()]
        path, _ = QFileDialog.getSaveFileName(
            self, "Export To", self._output_path.text(),
            f"Video (*.{fmt_ext})"
        )
        if path:
            self._output_path.setText(path)

    def _update_estimate(self) -> None:
        res_name = self._res_combo.currentText()
        w, h = RESOLUTIONS[res_name]
        fps = self._fps_combo.currentData()
        pixels_per_frame = w * h
        # Rough estimate: higher res = slower
        speed_factor = pixels_per_frame / (1920 * 1080)
        est_seconds = 8.0 * speed_factor * (fps / 30.0)
        if est_seconds < 60:
            self._estimate_label.setText(
                f"Estimated render time: ~{est_seconds:.0f} seconds"
            )
        else:
            mins = est_seconds / 60
            self._estimate_label.setText(
                f"Estimated render time: ~{mins:.1f} minutes"
            )

    def get_settings(self) -> dict:
        """Return export configuration."""
        res_name = self._res_combo.currentText()
        w, h = RESOLUTIONS[res_name]
        fmt_name = self._fmt_combo.currentText()
        return {
            "width": w,
            "height": h,
            "fps": self._fps_combo.currentData(),
            "format": FORMAT_OPTIONS[fmt_name],
            "output_path": self._output_path.text(),
            "scene_file": self._scene_file,
            "resolution_name": res_name,
        }


class ExportWorker(QThread):
    """Background thread that runs Manim's renderer for video export.

    Emits signals for progress updates, completion, and errors.
    Uses subprocess to run `manim render` CLI — avoids OpenGL
    context conflicts with the main thread.
    """

    progress = pyqtSignal(int, str)   # (percent, status_message)
    finished = pyqtSignal(str)        # output_path
    error = pyqtSignal(str)           # error_message

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = False

    def run(self) -> None:
        """Execute manim render in subprocess."""
        s = self._settings
        scene_file = s["scene_file"]
        output_path = s["output_path"]

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Build manim CLI command
        # LIVE PREVIEW: Uses OpenGL renderer (GPU-accelerated, 60fps)
        # EXPORT: Uses Cairo renderer (CPU-based, 100% accurate)
        # This "Draft Mode" separation is intentional — live preview is
        # for interactive editing, export is for final output.
        cmd = build_export_command(s)

        logger.info(f"Export command: {' '.join(cmd)}")
        self.progress.emit(0, "Starting Manim renderer...")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=os.path.dirname(scene_file),
            )

            output_lines = []
            start_time = time.time()

            for line in self._process.stdout:
                if self._cancelled:
                    self._process.terminate()
                    self.progress.emit(0, "Export cancelled")
                    return

                line = line.strip()
                output_lines.append(line)

                # Parse progress from Manim output
                if "Animation" in line:
                    elapsed = time.time() - start_time
                    # Rough progress based on animation mentions
                    anim_count = sum(
                        1 for l in output_lines if "Animation" in l
                    )
                    pct = min(90, anim_count * 8)
                    eta = (elapsed / max(pct, 1)) * (100 - pct)
                    self.progress.emit(
                        pct,
                        f"Rendering... ({pct}%) | ETA: {eta:.0f}s"
                    )
                elif "File ready at" in line or "Partial movie" in line:
                    self.progress.emit(95, "Encoding video...")

            self._process.wait()

            if self._process.returncode == 0:
                self.progress.emit(100, "Export complete!")
                # Find the actual output file
                self.finished.emit(output_path)
                logger.info(f"Export complete: {output_path}")
            else:
                err = "\n".join(output_lines[-5:])
                self.error.emit(f"Manim render failed:\n{err}")
                logger.error(f"Export failed: {err}")

        except FileNotFoundError:
            self.error.emit(
                "Manim CLI not found. Install with: pip install manim"
            )
        except Exception as e:
            self.error.emit(f"Export error: {str(e)}")
            logger.error(f"Export error: {e}")

    def cancel(self) -> None:
        """Cancel the export."""
        self._cancelled = True
        if self._process:
            self._process.terminate()
