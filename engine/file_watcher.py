"""
Bi-Sync File Watcher — QFileSystemWatcher with Debounce
========================================================

Phase 3: Bi-Directional Sync Bridge

Watches the scene .py file for changes and triggers hot-swap reload.
Includes Socket 5 pause/resume to prevent feedback loops during
slider dragging.

Debounce Logic:
    Atomic write (tempfile+rename) generates 2 filesystem events.
    We debounce with a 300ms QTimer to collapse them into one reload.

Safety:
    - Pause during slider drag (Socket 5)
    - Debounce prevents duplicate reloads
    - File read errors are caught and logged
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from PyQt6.QtCore import QFileSystemWatcher, QTimer

logger = logging.getLogger("bisync.file_watcher")

if TYPE_CHECKING:
    from engine.state import EngineState


class SceneFileWatcher:
    """Watches a scene .py file and triggers reload on changes.

    Uses QFileSystemWatcher (OS-native: FSEvents on macOS, inotify on Linux)
    for efficient file monitoring without polling.

    Socket 5 Integration:
        pause() → stops reacting to changes (during slider drag)
        resume() → re-enables change detection
    """

    def __init__(
        self,
        engine_state: EngineState,
        on_file_changed: Callable[[str], None],
    ) -> None:
        self._engine_state = engine_state
        self._on_file_changed = on_file_changed
        self._watcher = QFileSystemWatcher()
        self._watched_path: Optional[str] = None

        # Debounce timer: collapse multiple filesystem events into one
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)  # 300ms debounce
        self._debounce_timer.timeout.connect(self._do_reload)

        # Connect watcher signal
        self._watcher.fileChanged.connect(self._on_change_detected)

        # Wire Socket 5 to our pause/resume
        self._engine_state.set_file_watcher(self)

        logger.info("SceneFileWatcher initialized (300ms debounce)")

    def watch(self, file_path: str | Path) -> None:
        """Start watching a file for changes.

        Args:
            file_path: Path to the .py scene file to watch
        """
        path = str(Path(file_path).resolve())

        # Remove old watch if any
        if self._watched_path:
            self._watcher.removePath(self._watched_path)

        self._watched_path = path
        added = self._watcher.addPath(path)

        if added:
            logger.info(f"Watching: {Path(path).name}")
        else:
            logger.error(f"Failed to watch: {path}")

    def _on_change_detected(self, path: str) -> None:
        """Called by QFileSystemWatcher when the file changes.

        Starts the debounce timer. If another change arrives
        within 300ms, the timer resets (only one reload fires).
        """
        # Check Socket 5: are we paused?
        if self._engine_state.is_file_watcher_paused:
            logger.debug("File changed but watcher is PAUSED (Socket 5)")
            return

        logger.debug(f"Change detected: {Path(path).name} (debouncing...)")
        self._debounce_timer.start()  # Restart the timer

        # QFileSystemWatcher sometimes drops the watch after a change
        # (especially on macOS with atomic writes). Re-add it.
        if path not in self._watcher.files():
            self._watcher.addPath(path)

    def _do_reload(self) -> None:
        """Actually perform the reload after debounce period."""
        if self._watched_path:
            logger.info(f"Debounce complete → triggering reload")
            self._on_file_changed(self._watched_path)

    def pause(self) -> None:
        """Socket 5: Pause the watcher during slider drag."""
        self._engine_state.pause_file_watcher()
        self._debounce_timer.stop()
        logger.debug("File watcher PAUSED")

    def resume(self) -> None:
        """Socket 5: Resume the watcher after slider release."""
        self._engine_state.resume_file_watcher()
        logger.debug("File watcher RESUMED")

    def stop(self) -> None:
        """Stop watching entirely."""
        if self._watched_path:
            self._watcher.removePath(self._watched_path)
            self._watched_path = None
        self._debounce_timer.stop()
        logger.info("File watcher stopped")
