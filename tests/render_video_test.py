from manim import *
import main # Apply patches

config.renderer = "opengl"
config.write_to_movie = True
config.format = "mp4"
config.fps = 60
config.output_file = "test_opengl_output.mp4"

from scenes.advanced_scene import AdvancedScene

scene = AdvancedScene()
scene.render()
