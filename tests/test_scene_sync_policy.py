from __future__ import annotations

from pathlib import Path
import tempfile
import textwrap

from engine.ast_mutator import ASTMutator
from engine.hot_swap import HotSwapInjector
from engine.scene_sync import decide_scene_sync


BASE_SCENE = """
from manim import *

class Demo(Scene):
    def construct(self):
        circle = Circle(radius=1.0, color=RED, fill_opacity=0.4)
        circle.move_to([1.0, 0.0, 0.0])
        self.play(Create(circle), run_time=1.0)
"""


def parse_scene(source: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "scene.py"
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        mutator = ASTMutator()
        mutator.parse_file(path)
        bindings = {
            ref.variable_name: ref
            for ref in mutator.bindings.values()
        }
        animations = list(mutator.animations)
        return bindings, animations


def assert_mode(name: str, old_source: str, new_source: str, expected_mode: str) -> None:
    old_bindings, old_animations = parse_scene(old_source)
    new_bindings, new_animations = parse_scene(new_source)
    decision = decide_scene_sync(
        old_bindings=old_bindings,
        new_bindings=new_bindings,
        old_animations=old_animations,
        new_animations=new_animations,
        can_fast_apply_property=HotSwapInjector.can_fast_apply_property,
    )
    assert decision.mode == expected_mode, (
        f"{name}: expected {expected_mode}, got {decision.mode} "
        f"({decision.reasons})"
    )
    return decision


def main() -> None:
    decision = assert_mode(
        "safe color change",
        BASE_SCENE,
        BASE_SCENE.replace("color=RED", "color=BLUE"),
        "property_only",
    )
    assert decision.property_updates == {"circle": {"color": "BLUE"}}

    decision = assert_mode(
        "radius change requires reload",
        BASE_SCENE,
        BASE_SCENE.replace("radius=1.0", "radius=2.5"),
        "full_reload",
    )

    transformed_circle = """
from manim import *

class Demo(Scene):
    def construct(self):
        circle = Circle(radius=1.0, color=RED, fill_opacity=0.4)
        circle.scale(2.0)
        self.play(Create(circle), run_time=1.0)
"""
    assert_mode(
        "transformed radius change requires reload",
        transformed_circle,
        transformed_circle.replace("radius=1.0", "radius=2.5"),
        "full_reload",
    )

    assert_mode(
        "layout move_to change",
        BASE_SCENE,
        BASE_SCENE.replace("[1.0, 0.0, 0.0]", "[2.0, 1.0, 0.0]"),
        "full_reload",
    )

    assert_mode(
        "animation change",
        BASE_SCENE,
        BASE_SCENE.replace("run_time=1.0", "run_time=2.0"),
        "full_reload",
    )

    axes_base = """
from manim import *

class Demo(Scene):
    def construct(self):
        axes = Axes(x_range=[-3, 3, 1], y_range=[-2, 2, 1])
        self.play(Create(axes), run_time=1.0)
"""
    assert_mode(
        "tuple constructor change",
        axes_base,
        axes_base.replace("x_range=[-3, 3, 1]", "x_range=[-1, 4, 1]"),
        "full_reload",
    )

    print("scene sync policy tests passed")


if __name__ == "__main__":
    main()
