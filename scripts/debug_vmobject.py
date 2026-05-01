from manim import *
import logging
logging.basicConfig(level=logging.DEBUG)
config.renderer = "opengl"
from manim.renderer.opengl_renderer import OpenGLRenderer

# We can run standard manim OpenGLRenderer
renderer = OpenGLRenderer()
# Wait, OpenGLRenderer requires a window or headless mode context.
