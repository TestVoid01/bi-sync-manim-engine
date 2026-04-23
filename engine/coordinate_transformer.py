"""
Bi-Sync Coordinate Transformer — Pixel to Math Space
======================================================

Phase 4: Interactive Canvas Controller

Converts OS-level pixel coordinates (top-left origin, 0→1920)
to Manim's mathematical coordinate space (center origin, -7→+7).

Uses the Camera's View-Projection Matrix inverse for accurate
transformation that accounts for camera position, zoom, and rotation.

Fallback: If camera matrix is unavailable, uses simple linear
interpolation based on widget dimensions and Manim's frame config.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger("bisync.coord_transform")


class CoordinateTransformer:
    """Transforms pixel coordinates to Manim math space and back.

    Two modes:
        1. Matrix mode: Uses Camera's inverse view-projection matrix
           (accurate with camera transforms, zoom, rotation)
        2. Fallback mode: Simple linear mapping based on frame dimensions
           (works without camera, good enough for static scenes)

    The transformation:
        Pixel (0,0) = top-left of widget
        Math (0,0) = center of Manim frame
        Pixel Y-axis is INVERTED (down = positive)
        Math Y-axis is NORMAL (up = positive)
    """

    def __init__(self) -> None:
        self._widget_width: int = 1280
        self._widget_height: int = 720

        # Manim frame dimensions (from config)
        self._frame_width: float = 14.222  # Default Manim frame width
        self._frame_height: float = 8.0    # Default Manim frame height

        # Camera matrix (set by canvas when available)
        self._inv_view_proj: Optional[np.ndarray] = None

        logger.info("CoordinateTransformer initialized")

    def set_widget_size(self, width: int, height: int) -> None:
        """Update widget dimensions (called on resizeGL)."""
        self._widget_width = width
        self._widget_height = height

    def set_frame_dimensions(self, width: float, height: float) -> None:
        """Set Manim frame dimensions from config."""
        self._frame_width = width
        self._frame_height = height

    def set_camera_matrix(self, inv_view_proj: np.ndarray) -> None:
        """Set the inverse view-projection matrix from Camera.

        This enables accurate pixel→math conversion that accounts
        for camera position, zoom, and rotation.
        """
        self._inv_view_proj = inv_view_proj

    def pixel_to_math(self, px: int, py: int) -> tuple[float, float]:
        """Convert pixel coordinates to Manim math coordinates.

        Args:
            px: Pixel X (0 = left edge of widget)
            py: Pixel Y (0 = top edge of widget)

        Returns:
            (math_x, math_y) in Manim coordinate space
        """
        if self._inv_view_proj is not None:
            return self._pixel_to_math_matrix(px, py)
        return self._pixel_to_math_linear(px, py)

    def _pixel_to_math_linear(self, px: int, py: int) -> tuple[float, float]:
        """Fallback: Simple linear interpolation.

        Maps pixel space to math space using frame dimensions.
        Assumes camera is at origin with no rotation or zoom.
        """
        # Normalize pixel to [-1, 1] range
        nx = (2.0 * px / self._widget_width) - 1.0
        ny = 1.0 - (2.0 * py / self._widget_height)  # Invert Y

        # Scale to Manim frame
        math_x = nx * (self._frame_width / 2.0)
        math_y = ny * (self._frame_height / 2.0)

        return (math_x, math_y)

    def _pixel_to_math_matrix(self, px: int, py: int) -> tuple[float, float]:
        """Matrix mode: Use inverse view-projection matrix.

        Transforms pixel coordinates through the camera's inverse
        matrix for accurate conversion with camera transforms.
        """
        # Normalize to NDC [-1, 1]
        nx = (2.0 * px / self._widget_width) - 1.0
        ny = 1.0 - (2.0 * py / self._widget_height)

        # Apply inverse view-projection matrix
        ndc = np.array([nx, ny, 0.0, 1.0])
        world = self._inv_view_proj @ ndc

        # Perspective divide (w component)
        if abs(world[3]) > 1e-10:
            world /= world[3]

        return (float(world[0]), float(world[1]))

    def math_to_pixel(self, mx: float, my: float) -> tuple[int, int]:
        """Convert Manim math coordinates to pixel coordinates.

        Inverse of pixel_to_math. Used for visual feedback (e.g.,
        drawing selection highlights at correct pixel positions).
        """
        # Scale from Manim frame to [-1, 1]
        nx = mx / (self._frame_width / 2.0)
        ny = my / (self._frame_height / 2.0)

        # Convert to pixel space
        px = int((nx + 1.0) * self._widget_width / 2.0)
        py = int((1.0 - ny) * self._widget_height / 2.0)

        return (px, py)
