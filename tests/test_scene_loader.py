from __future__ import annotations

from pathlib import Path
import tempfile

from engine.export_dialog import build_export_command
from engine.scene_loader import (
    discover_scene_class_from_file,
    discover_scene_class_from_source,
    module_name_from_path,
)


def test_module_name_from_path_uses_project_relative_python_path():
    project_root = Path("/tmp/project")
    scene_file = project_root / "scenes" / "alt_scene.py"
    module_name = module_name_from_path(scene_file, project_root=project_root)
    assert module_name == "scenes.alt_scene"


def test_discover_scene_class_from_source_chooses_latest_local_scene():
    source = """
from manim import *

class Helper(Scene):
    pass

class FinalScene(ThreeDScene):
    def construct(self):
        pass
"""
    scene_class = discover_scene_class_from_source(
        source,
        scene_file="scenes/advanced_scene.py",
        module_name="scenes.advanced_scene",
    )
    assert scene_class is not None
    assert scene_class.__name__ == "FinalScene"


def test_discover_scene_class_from_file_accepts_renamed_scene_class():
    source = """
from manim import *

class CompletelyDifferentScene(MovingCameraScene):
    def construct(self):
        self.add(Dot())
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        scene_file = project_root / "scenes" / "advanced_scene.py"
        scene_file.parent.mkdir(parents=True, exist_ok=True)
        scene_file.write_text(source, encoding="utf-8")

        scene_class = discover_scene_class_from_file(
            scene_file,
            module_name="scenes.advanced_scene",
        )
        assert scene_class is not None
        assert scene_class.__name__ == "CompletelyDifferentScene"


def test_discover_scene_class_prefers_active_name_when_multiple_scenes_exist():
    source = """
from manim import *

class FirstScene(Scene):
    def construct(self):
        pass

class SecondScene(Scene):
    def construct(self):
        pass
"""
    scene_class = discover_scene_class_from_source(
        source,
        scene_file="scenes/advanced_scene.py",
        module_name="scenes.advanced_scene",
        preferred_name="FirstScene",
    )
    assert scene_class is not None
    assert scene_class.__name__ == "FirstScene"


def test_export_command_uses_dynamic_scene_name():
    cmd = build_export_command(
        {
            "scene_file": "/tmp/project/scenes/advanced_scene.py",
            "scene_name": "CompletelyDifferentScene",
            "format": "mp4",
            "fps": 60,
            "width": 1920,
            "height": 1080,
            "output_path": "/tmp/project/exports/out.mp4",
        }
    )
    assert cmd[0:4] == [
        "manim",
        "render",
        "/tmp/project/scenes/advanced_scene.py",
        "CompletelyDifferentScene",
    ]


if __name__ == "__main__":
    test_module_name_from_path_uses_project_relative_python_path()
    test_discover_scene_class_from_source_chooses_latest_local_scene()
    test_discover_scene_class_from_file_accepts_renamed_scene_class()
    test_discover_scene_class_prefers_active_name_when_multiple_scenes_exist()
    test_export_command_uses_dynamic_scene_name()
    print("test_scene_loader.py: PASS")
