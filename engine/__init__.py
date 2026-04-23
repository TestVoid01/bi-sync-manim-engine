"""
Bi-Sync Manim Engine — Core Engine Package
============================================
Phase 1: Core Rendering & GUI Fusion (RGF)

This package contains the OpenGL Context Hijack architecture
that fuses Manim's rendering pipeline into PyQt6's QOpenGLWidget.
"""

from engine.state import EngineState
from engine.renderer import HijackedRenderer
from engine.canvas import ManimCanvas

__all__ = ["EngineState", "HijackedRenderer", "ManimCanvas"]
