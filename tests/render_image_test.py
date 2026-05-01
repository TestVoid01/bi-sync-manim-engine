from manim import *
import main # To apply our monkey patches!

config.renderer = "opengl"
config.write_to_movie = False
config.format = "png"
config.output_file = "test_opengl_output.png"

from scenes.advanced_scene import AdvancedScene

scene = AdvancedScene()
scene.render()
