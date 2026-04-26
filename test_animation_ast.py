from pathlib import Path
import tempfile
from textwrap import dedent

from engine.ast_mutator import ASTMutator


def _assert_contains(text: str, needle: str) -> None:
    if needle not in text:
        raise AssertionError(f"Expected to find {needle!r} in:\n{text}")


def _run_position_case(name: str, source: str, expected_snippet: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "scene.py"
        path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(path)

        animation_ref = mutator.animations[0]
        assert animation_ref.is_draggable, f"{name}: animation should be draggable"
        original_key = animation_ref.animation_key

        updated = mutator.update_animation_position(
            animation_ref,
            absolute_x=4.2,
            absolute_y=-1.5,
            base_center=(3.0, 4.0, 0.0),
        )
        assert updated, f"{name}: update_animation_position should succeed"
        assert mutator.is_dirty, f"{name}: mutator should be dirty after update"
        assert mutator.save_atomic(path), f"{name}: save_atomic should succeed"
        assert not mutator.is_dirty, f"{name}: mutator should be clean after save"

        saved_text = path.read_text(encoding="utf-8")
        _assert_contains(saved_text, expected_snippet)

        rebound = mutator.get_animation_by_key(original_key)
        assert rebound is not None, f"{name}: animation key should survive metadata refresh"
        assert rebound.animation_key == original_key, f"{name}: rebound animation key mismatch"


def main() -> None:
    _run_position_case(
        "animate_move_to",
        dedent(
            """
            from manim import *

            class AdvancedScene(Scene):
                def construct(self):
                    blob = Dot()
                    self.play(blob.animate.move_to([1, 2, 0]), run_time=1.0)
            """
        ),
        "self.play(blob.animate.move_to([4.2, -1.5, 0]), run_time=1.0)",
    )

    _run_position_case(
        "animate_shift",
        dedent(
            """
            from manim import *

            class AdvancedScene(Scene):
                def construct(self):
                    blob = Dot().move_to([3, 4, 0])
                    self.play(blob.animate.shift(RIGHT * 2), run_time=1.0)
            """
        ),
        "self.play(blob.animate.shift([1.2, -5.5, 0.0]), run_time=1.0)",
    )

    _run_position_case(
        "effect_shift",
        dedent(
            """
            from manim import *

            class AdvancedScene(Scene):
                def construct(self):
                    blob = Dot().move_to([1, 1, 0])
                    self.play(FadeOut(blob, shift=RIGHT * 2), run_time=1.0)
            """
        ),
        "self.play(FadeOut(blob, shift=[1.2, -5.5, 0.0]), run_time=1.0)",
    )

    _run_position_case(
        "animate_shift_rotate",
        dedent(
            """
            from manim import *

            class AdvancedScene(Scene):
                def construct(self):
                    blob = Dot().move_to([3, 4, 0])
                    self.play(blob.animate.shift(RIGHT * 2).rotate(PI / 3), run_time=1.0)
            """
        ),
        "self.play(blob.animate.shift([1.2, -5.5, 0.0]).rotate(PI / 3), run_time=1.0)",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        rotate_only_path = Path(tmpdir) / "scene.py"
        rotate_only_path.write_text(
            dedent(
                """
                from manim import *

                class AdvancedScene(Scene):
                    def construct(self):
                        blob = Dot()
                        self.play(blob.animate.rotate(PI / 3), run_time=1.0)
                """
            ),
            encoding="utf-8",
        )
        rotate_only = ASTMutator()
        rotate_only.parse_file(rotate_only_path)
        rotate_animation = rotate_only.animations[0]
        assert not rotate_animation.is_draggable, "rotate-only animation should not be draggable"
        assert rotate_animation.position_mode == "none", "rotate-only animation should have no position mode"

    print("test_animation_ast.py: PASS")


if __name__ == "__main__":
    main()
