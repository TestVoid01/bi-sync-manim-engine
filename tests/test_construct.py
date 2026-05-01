import sys
from manim import *
config.renderer = "opengl"
from scenes.advanced_scene import AdvancedScene
scene = AdvancedScene()
scene.construct()
