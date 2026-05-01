from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QSlider

from engine.ast_mutator import ASTMutator, ASTParamRef, ASTValueRef
from engine.drag_controller import DragController
from engine.hit_tester import HitResult
from engine.object_registry import LiveObjectRef, ObjectRegistry, SelectionRef
from engine.property_inspector import PropertyInspector
from engine.property_panel import PropertyPanel
from engine.code_editor import CodeEditorPanel, ShadowBuildResult
from engine.canvas import ManimCanvas
from engine.persistence_policy import PersistenceStrategy
from engine.property_policy import decide_property_application
from engine.state import EngineState
from main import MainWindow


APP = QApplication.instance() or QApplication([])


class DummyMob:
    def __init__(self, center=(1.0, 1.0, 0.0)) -> None:
        self._center = [float(center[0]), float(center[1]), float(center[2])]

    def get_center(self):
        return tuple(self._center)

    def move_to(self, new_center) -> None:
        self._center = [float(new_center[0]), float(new_center[1]), float(new_center[2])]


class DummyVisualMob:
    def __init__(self) -> None:
        self.fill_opacity = 0.6
        self.color = "#ff0000"

    def set_fill_opacity(self, value) -> None:
        self.fill_opacity = value

    def set_color(self, value) -> None:
        self.color = value


class DummyHitTester:
    def __init__(self, mob) -> None:
        self._mob = mob
        self._ast_ref = SimpleNamespace(variable_name="circle", line_number=12)

    def test(self, math_x, math_y, scene):
        return HitResult(
            top_level_mobject_id=id(self._mob),
            selected_mobject_id=id(self._mob),
            variable_name="circle",
            line_number=12,
            source_key="scene.py:construct:12:0:named_direct:1",
            editability="source_editable",
            read_only_reason="",
            path=(),
            display_name="circle",
            registry_backed=True,
            constructor_name="Circle",
        )

    def find_mobject_and_path(self, mob_id, scene):
        return self._mob, self._mob, []

    def resolve_hit_mobjects(self, hit_result, scene):
        return self._mob, self._mob

    def get_ast_ref(self, mob):
        return self._ast_ref

    def get_variable_name(self, mob):
        return "circle"


class DummyCoordTransformer:
    def pixel_to_math(self, px: int, py: int):
        return float(px), float(py)


class DummyWatcher:
    def __init__(self) -> None:
        self.pause_count = 0
        self.resume_count = 0

    def pause(self) -> None:
        self.pause_count += 1

    def resume(self) -> None:
        self.resume_count += 1


class DummyEngineState:
    def request_render(self) -> None:
        pass


class DummyMutator:
    def __init__(self) -> None:
        self.last_error = None

    def plan_position_persistence(self, *args, **kwargs):
        return PersistenceStrategy(mode="safe_patch")


def build_drag_controller():
    engine_state = EngineState()
    mob = DummyMob()
    watcher = DummyWatcher()
    controller = DragController(
        engine_state=engine_state,
        hit_tester=DummyHitTester(mob),
        coord_transformer=DummyCoordTransformer(),
        ast_mutator=DummyMutator(),
        file_watcher=watcher,
    )
    controller.set_scene(object())
    commits = []
    controller._update_ast_position = lambda *args, **kwargs: commits.append((args, kwargs))
    return controller, watcher, commits


def test_click_only_selection_is_safe():
    controller, watcher, commits = build_drag_controller()
    assert controller.on_mouse_press(10, 10) is True
    assert controller.has_pending_drag_candidate is True
    assert controller.is_dragging is False
    assert watcher.pause_count == 0

    controller.on_mouse_release(10, 10)
    assert controller.has_pending_drag_candidate is False
    assert watcher.pause_count == 0
    assert watcher.resume_count == 0
    assert commits == []


def test_drag_below_threshold_stays_selection_only():
    controller, watcher, commits = build_drag_controller()
    controller.on_mouse_press(10, 10)
    controller.on_mouse_move(15, 15)
    controller.on_mouse_release(15, 15)

    assert controller.is_dragging is False
    assert watcher.pause_count == 0
    assert watcher.resume_count == 0
    assert commits == []


def test_drag_above_threshold_commits_once():
    controller, watcher, commits = build_drag_controller()
    controller.on_mouse_press(10, 10)
    controller.on_mouse_move(25, 25)
    assert controller.is_dragging is True
    assert watcher.pause_count == 1

    controller.on_mouse_release(25, 25)
    assert controller.is_dragging is False
    assert watcher.resume_count == 1
    assert len(commits) == 1


def test_canvas_forwards_move_while_drag_candidate_is_armed():
    moves = []

    class DummyDragController:
        is_dragging = False
        has_pending_drag_candidate = True

        def on_mouse_move(self, px, py):
            moves.append((px, py))

    class DummyEvent:
        def position(self):
            return SimpleNamespace(x=lambda: 25, y=lambda: 30)

    fake_canvas = SimpleNamespace(
        _drag_controller=DummyDragController(),
        _last_hover_px=0,
        _last_hover_py=0,
        _last_hover_hit=False,
        _coord_transformer=None,
        _engine_state=SimpleNamespace(get_hitboxes=lambda: {}),
    )

    ManimCanvas.mouseMoveEvent(fake_canvas, DummyEvent())
    assert moves == [(25, 30)]


def test_canvas_forwards_release_while_drag_candidate_is_armed():
    released = []
    cursor_updates = []

    class DummyDragController:
        is_dragging = False
        has_pending_drag_candidate = True

        def on_mouse_release(self):
            released.append(True)

    fake_canvas = SimpleNamespace(
        _drag_controller=DummyDragController(),
        setCursor=lambda cursor: cursor_updates.append(cursor),
    )

    ManimCanvas.mouseReleaseEvent(fake_canvas, SimpleNamespace())
    assert released == [True]
    assert len(cursor_updates) == 1


def test_property_value_equivalence_blocks_noop_persist():
    assert PropertyPanel._values_equivalent(1.0, 1.0)
    assert PropertyPanel._values_equivalent([1.0, 2.0], [1, 2])
    assert not PropertyPanel._values_equivalent([1.0, 2.0], [1.0, 2.2])


def test_toolbar_sync_uses_live_animation_count():
    dummy = SimpleNamespace()
    dummy.animation_player = SimpleNamespace(
        PLAYING="playing",
        PAUSED="paused",
        IDLE="idle",
        state="idle",
        progress=0.0,
        animation_count=11,
    )
    dummy.engine_state = SimpleNamespace(selected_animation="stale")
    dummy._btn_play = QPushButton()
    dummy._btn_pause = QPushButton()
    dummy._progress_slider = QSlider(Qt.Orientation.Horizontal)
    dummy._progress_slider.setRange(0, 1000)
    dummy._anim_label = QLabel()

    MainWindow._sync_animation_toolbar(
        dummy,
        state="idle",
        progress=0.0,
        reset_selection=True,
        force_progress_sync=True,
    )
    assert dummy.engine_state.selected_animation is None
    assert dummy._anim_label.text() == "  Ready (11 animations)"
    assert dummy._progress_slider.value() == 0


def test_property_policy_prefers_correctness_for_geometry():
    transformed_binding = SimpleNamespace(
        modifier_calls=[SimpleNamespace(owner_name="scale")]
    )
    radius_decision = decide_property_application(
        "radius",
        widget_hint="slider",
        owner_kind="constructor",
        binding=transformed_binding,
    )
    assert radius_decision.live_safe is False
    assert radius_decision.reload_only is True
    assert radius_decision.display_name == "radius (base)"

    color_decision = decide_property_application(
        "color",
        widget_hint="color",
        owner_kind="constructor",
        binding=transformed_binding,
    )
    assert color_decision.live_safe is True

    effective_width_decision = decide_property_application(
        "width",
        widget_hint="slider",
        owner_kind="live",
        binding=transformed_binding,
    )
    assert effective_width_decision.read_only is True
    assert effective_width_decision.display_name == "width (effective)"


def test_drag_ast_injection_stays_after_assignment_and_modifiers():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        axes = Axes()
        equation = MathTex("x")
        equation.next_to(axes, UP, buff=0.3)
        self.play(FadeIn(equation))
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        engine_state = EngineState()
        watcher = DummyWatcher()
        controller = DragController(
            engine_state=engine_state,
            hit_tester=DummyHitTester(DummyMob()),
            coord_transformer=DummyCoordTransformer(),
            ast_mutator=mutator,
            file_watcher=watcher,
        )
        equation_ref = mutator.get_binding_by_name("equation")
        assert equation_ref is not None

        controller._update_ast_position(
            "equation",
            -0.65,
            2.56,
            source_key=equation_ref.source_key,
            path=[],
        )

        updated = scene_path.read_text(encoding="utf-8")
        lines = [line.strip() for line in updated.splitlines()]
        equation_assign = lines.index(next(line for line in lines if line.startswith("equation = MathTex(")))
        next_to = lines.index("equation.next_to(axes, UP, buff=0.3)")
        move_to = lines.index("equation.move_to([-0.65, 2.56, 0.0])")
        play_call = lines.index("self.play(FadeIn(equation))")
        assert equation_assign < next_to < move_to < play_call


def test_chained_assignment_uses_real_constructor_metadata():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        dot = Dot()
        label = MathTex("x").next_to(dot, UP, buff=0.2)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        label_ref = mutator.get_binding_by_name("label")
        assert label_ref is not None
        assert label_ref.constructor_name == "MathTex"
        assert label_ref.node_kind == "named_chained"
        assert any(call.owner_name == "next_to" for call in label_ref.modifier_calls)


def test_factory_method_assignment_is_not_misclassified_as_constructor():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        axes = Axes()
        curve = axes.plot(lambda x: x**2, x_range=[-2, 2], color=BLUE, stroke_width=7)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        curve_ref = mutator.get_binding_by_name("curve")
        assert curve_ref is not None
        assert curve_ref.node_kind == "named_factory_method"
        assert curve_ref.primary_owner_kind == "factory_method"
        assert curve_ref.constructor_name in {"ParametricFunction", "plot"}
        assert {param.param_name for param in curve_ref.constructor_params} >= {
            "x_range",
            "color",
            "stroke_width",
        }


def test_constructor_owned_factory_method_assignment_is_source_backed():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        curve = Axes().plot(lambda x: x**2, x_range=[-2, 2], color=BLUE)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        curve_ref = mutator.get_binding_by_name("curve")
        assert curve_ref is not None
        assert curve_ref.node_kind == "named_factory_method"
        assert curve_ref.primary_owner_kind == "factory_method"
        assert curve_ref.constructor_name == "ParametricFunction"
        assert {param.param_name for param in curve_ref.constructor_params} >= {
            "function",
            "x_range",
            "color",
        }


def test_inline_constructor_creates_synthetic_source_node():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        self.add(Circle(radius=2, color=RED))
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        inline_nodes = [node for node in mutator.iter_scene_nodes() if node.node_kind == "inline_direct"]
        assert len(inline_nodes) == 1
        assert inline_nodes[0].constructor_name == "Circle"
        assert inline_nodes[0].editability == "source_editable"


def test_inline_animation_constructor_creates_synthetic_source_node():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        self.play(Create(Circle(radius=2, color=RED)))
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        inline_nodes = [node for node in mutator.iter_scene_nodes() if node.node_kind == "inline_direct"]
        assert len(inline_nodes) == 1
        assert inline_nodes[0].constructor_name == "Circle"
        assert inline_nodes[0].editability == "source_editable"


def test_helper_return_creates_read_only_source_node():
    source = """
from manim import *

def make_label():
    return MathTex("x").scale(2)

class Demo(Scene):
    def construct(self):
        label = make_label()
        self.add(label)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        helper_nodes = [node for node in mutator.iter_scene_nodes() if node.node_kind == "helper_return"]
        assert len(helper_nodes) == 1
        assert helper_nodes[0].constructor_name == "MathTex"
        assert helper_nodes[0].editability == "source_read_only"
        assert helper_nodes[0].read_only_reason


def test_non_mobject_assignments_are_filtered_out():
    source = """
from manim import *
import numpy as np

class Demo(Scene):
    def construct(self):
        axes = Axes()
        values = np.array([1, 2, 3])
        det = np.linalg.det([[1, 0], [0, 1]])
        copy_values = values.copy()
        curve = axes.plot(lambda x: x**2, x_range=[-2, 2], color=BLUE)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        scene_names = {node.variable_name for node in mutator.iter_scene_nodes()}
        assert "axes" in scene_names
        assert "curve" in scene_names
        assert "values" not in scene_names
        assert "det" not in scene_names
        assert "copy_values" not in scene_names


def test_group_children_create_inline_child_nodes():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        group = VGroup(Circle(radius=2, color=RED), Square(side_length=1.5))
        self.add(group)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        group_ref = mutator.get_binding_by_name("group")
        assert group_ref is not None

        child_refs = [
            mutator.get_child_binding(group_ref.source_key, (0,)),
            mutator.get_child_binding(group_ref.source_key, (1,)),
        ]
        assert all(child is not None for child in child_refs)
        assert child_refs[0].constructor_name == "Circle"
        assert child_refs[1].constructor_name == "Square"


def test_custom_mobject_subclass_is_detected():
    source = """
from manim import *

class FancyBlob(VMobject):
    pass

class Demo(Scene):
    def construct(self):
        blob = FancyBlob(color=BLUE)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        blob_ref = mutator.get_binding_by_name("blob")
        assert blob_ref is not None
        assert blob_ref.constructor_name == "FancyBlob"
        assert blob_ref.node_kind == "named_direct"


def test_nested_live_readout_is_read_only_for_parent_backed_child_hits():
    inspector = PropertyInspector(
        ast_mutator=SimpleNamespace(),
        object_registry=SimpleNamespace(),
        scene_getter=lambda: None,
    )
    binding = SimpleNamespace(
        inline_path=(),
        modifier_calls=[],
    )
    selection = SimpleNamespace(
        editability="source_editable",
        source_key="scene.py:construct:10:0:named_direct:1",
        path=(0,),
        read_only_reason="",
    )

    spec = inspector._make_live_spec(
        "color",
        "#ff0000",
        live_mobject=SimpleNamespace(),
        binding=binding,
        selection=selection,
    )

    assert spec is not None
    assert spec.read_only is True
    assert spec.read_only_reason == "live readout only"


def test_exact_inline_child_live_readout_stays_editable():
    inspector = PropertyInspector(
        ast_mutator=SimpleNamespace(
            plan_property_persistence=lambda *args, **kwargs: PersistenceStrategy(
                mode="exact_source"
            )
        ),
        object_registry=SimpleNamespace(),
        scene_getter=lambda: None,
    )
    binding = SimpleNamespace(
        inline_path=(0,),
        modifier_calls=[],
    )
    selection = SimpleNamespace(
        variable_name="inline_circle",
        editability="source_editable",
        source_key="scene.py:construct:10:0:inline_direct:1",
        path=(0,),
        read_only_reason="",
    )

    spec = inspector._make_live_spec(
        "fill_opacity",
        0.6,
        live_mobject=DummyVisualMob(),
        binding=binding,
        selection=selection,
    )

    assert spec is not None
    assert spec.read_only is False


def test_live_geometry_readout_is_effective_and_read_only():
    inspector = PropertyInspector(
        ast_mutator=SimpleNamespace(),
        object_registry=SimpleNamespace(),
        scene_getter=lambda: None,
    )
    binding = SimpleNamespace(
        inline_path=(),
        modifier_calls=[SimpleNamespace(owner_name="scale")],
    )
    selection = SimpleNamespace(
        editability="source_editable",
        source_key="scene.py:construct:10:0:named_direct:1",
        path=(),
        read_only_reason="",
    )

    spec = inspector._make_live_spec(
        "width",
        12.0,
        live_mobject=DummyVisualMob(),
        binding=binding,
        selection=selection,
    )

    assert spec is not None
    assert spec.display_key == "width (effective)"
    assert spec.read_only is True
    assert "effective rendered size" in spec.read_only_reason


def test_live_unsupported_readout_stays_read_only():
    inspector = PropertyInspector(
        ast_mutator=SimpleNamespace(),
        object_registry=SimpleNamespace(),
        scene_getter=lambda: None,
    )
    binding = SimpleNamespace(
        inline_path=(),
        modifier_calls=[],
    )
    selection = SimpleNamespace(
        editability="source_editable",
        source_key="scene.py:construct:10:0:named_direct:1",
        path=(),
        read_only_reason="",
    )

    spec = inspector._make_live_spec(
        "tab_width",
        8.0,
        live_mobject=DummyVisualMob(),
        binding=binding,
        selection=selection,
    )

    assert spec is not None
    assert spec.read_only is True
    assert "no reliable source-backed write path" in spec.read_only_reason


def test_constructor_geometry_ast_spec_is_reload_only_not_read_only():
    inspector = PropertyInspector(
        ast_mutator=SimpleNamespace(),
        object_registry=SimpleNamespace(),
        scene_getter=lambda: None,
    )
    binding = SimpleNamespace(
        editability="source_editable",
        read_only_reason="",
        source_key="scene.py:construct:10:0:named_direct:1",
        modifier_calls=[SimpleNamespace(owner_name="scale")],
    )
    param_ref = ASTParamRef(
        target_var="circle",
        owner_kind="constructor",
        owner_name="Circle",
        line_number=10,
        col_offset=8,
        param_name="radius",
        param_index=None,
        value_ref=ASTValueRef(
            literal_value=1.2,
            raw_code="1.2",
            value_kind="number",
        ),
    )

    spec = inspector._make_ast_spec(
        param_ref,
        live_mobject=DummyVisualMob(),
        binding=binding,
        section="Source Properties",
    )

    assert spec is not None
    assert spec.apply_mode == "reload_only"
    assert spec.read_only is False
    assert spec.display_key == "radius (base)"
    assert spec.live_safe is False


def test_source_chain_ast_spec_is_truthfully_read_only():
    inspector = PropertyInspector(
        ast_mutator=SimpleNamespace(),
        object_registry=SimpleNamespace(),
        scene_getter=lambda: None,
    )
    binding = SimpleNamespace(
        editability="source_editable",
        read_only_reason="",
        source_key="scene.py:construct:10:0:named_chained:1",
        modifier_calls=[],
    )
    param_ref = ASTParamRef(
        target_var="label",
        owner_kind="modifier",
        owner_name="next_to",
        line_number=12,
        col_offset=8,
        param_name="buff",
        param_index=None,
        value_ref=ASTValueRef(
            literal_value=0.3,
            raw_code="0.3",
            value_kind="number",
        ),
    )

    spec = inspector._make_ast_spec(
        param_ref,
        live_mobject=DummyVisualMob(),
        binding=binding,
        section="Source Chain",
    )

    assert spec is not None
    assert spec.read_only is True
    assert spec.apply_strategy == "read_only"
    assert "source chain editing" in spec.read_only_reason


def test_complex_constructor_ast_spec_is_truthfully_read_only():
    inspector = PropertyInspector(
        ast_mutator=SimpleNamespace(),
        object_registry=SimpleNamespace(),
        scene_getter=lambda: None,
    )
    binding = SimpleNamespace(
        editability="source_editable",
        read_only_reason="",
        source_key="scene.py:construct:10:0:named_factory_method:1",
        modifier_calls=[],
    )
    param_ref = ASTParamRef(
        target_var="curve",
        owner_kind="constructor",
        owner_name="ParametricFunction",
        line_number=14,
        col_offset=8,
        param_name="x_range",
        param_index=None,
        value_ref=ASTValueRef(
            literal_value=[-2.0, 3.0, 1.0],
            raw_code="[-2, 3, 1]",
            value_kind="sequence",
            container_kind="list",
        ),
    )

    spec = inspector._make_ast_spec(
        param_ref,
        live_mobject=DummyVisualMob(),
        binding=binding,
        section="Source Properties",
    )

    assert spec is not None
    assert spec.widget_hint == "tuple"
    # After Slice 5 unblock: constructor-owned tuples are editable via PropertyTupleEditor
    assert spec.read_only is False
    assert spec.apply_strategy == "ast_reload"


def test_foreign_runtime_marker_does_not_fallback_by_line():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        det_label = MathTex("\\\\det(A)")
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)
        det_ref = mutator.get_binding_by_name("det_label")
        assert det_ref is not None

        foreign_ref = mutator.get_binding_by_runtime_marker(
            "/tmp/not_the_scene.py",
            det_ref.line_number,
            1,
        )
        assert foreign_ref is None

        registry_ref = ObjectRegistry._get_ast_ref(
            mutator,
            "/tmp/not_the_scene.py",
            det_ref.line_number,
            1,
        )
        assert registry_ref is None


def test_owned_runtime_marker_without_exact_occurrence_stays_unmapped():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        det_label = MathTex("\\\\det(A)")
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)
        det_ref = mutator.get_binding_by_name("det_label")
        assert det_ref is not None

        owned_ref = mutator.get_binding_by_runtime_marker(
            str(scene_path),
            det_ref.line_number,
            999,
        )
        assert owned_ref is None

        registry_ref = ObjectRegistry._get_ast_ref(
            mutator,
            str(scene_path),
            det_ref.line_number,
            999,
        )
        assert registry_ref is None


def test_selection_rebind_notifies_even_when_source_key_matches():
    engine_state = EngineState()
    seen: list[SelectionRef | None] = []
    engine_state.on_selection_changed(seen.append)

    first = SelectionRef(
        mobject_id=1,
        top_level_id=1,
        variable_name="title",
        line_number=12,
        constructor_name="Text",
        source_key="scene.py:construct:12:0:named_direct:1",
        path=(),
        display_name="title",
    )
    rebound = SelectionRef(
        mobject_id=101,
        top_level_id=101,
        variable_name="title",
        line_number=12,
        constructor_name="Text",
        source_key="scene.py:construct:12:0:named_direct:1",
        path=(),
        display_name="title",
    )

    engine_state.set_selected_object(first)
    engine_state.set_selected_object(rebound)

    assert len(seen) == 2


def test_object_registry_selection_carries_exact_and_nearest_source_keys():
    registry = ObjectRegistry()
    parent = LiveObjectRef(
        mobject_id=1,
        top_level_id=1,
        variable_name="label",
        line_number=12,
        constructor_name="MathTex",
        source_key="scene.py:construct:12:0:named_direct:1:root",
        editability="source_editable",
        source_display_name="label",
        path=(),
        parent_id=None,
        is_top_level=True,
    )
    child = LiveObjectRef(
        mobject_id=2,
        top_level_id=1,
        variable_name=None,
        line_number=12,
        constructor_name="VMobject",
        source_key=None,
        editability="live_read_only",
        read_only_reason="runtime child",
        source_display_name="label",
        path=(0,),
        parent_id=1,
        is_top_level=False,
    )
    exact_inline = LiveObjectRef(
        mobject_id=3,
        top_level_id=3,
        variable_name="group[0]",
        line_number=20,
        constructor_name="Circle",
        source_key="group[0]:20:4:inline_direct:1:0",
        editability="source_editable",
        source_display_name="group[0]",
        path=(0,),
        parent_id=1,
        is_top_level=False,
    )
    registry._refs_by_id[parent.mobject_id] = parent
    registry._refs_by_id[child.mobject_id] = child
    registry._refs_by_id[exact_inline.mobject_id] = exact_inline
    registry._top_level_ids_by_var["label"] = parent.mobject_id
    registry._source_key_to_id[parent.source_key] = parent.mobject_id
    registry._source_key_to_id[exact_inline.source_key] = exact_inline.mobject_id

    nested_selection = registry.create_selection(
        top_level_mobject_id=1,
        selected_mobject_id=2,
        path=(0,),
    )
    assert nested_selection is not None
    assert nested_selection.source_key == parent.source_key
    assert nested_selection.nearest_editable_source_key == parent.source_key
    assert nested_selection.exact_source_key is None
    assert nested_selection.display_name == "label[0]"
    assert nested_selection.constructor_name == "VMobject"

    inline_selection = registry.create_selection(
        top_level_mobject_id=1,
        selected_mobject_id=3,
        path=(0,),
    )
    assert inline_selection is not None
    assert inline_selection.source_key == exact_inline.source_key
    assert inline_selection.exact_source_key == exact_inline.source_key
    assert inline_selection.nearest_editable_source_key == exact_inline.source_key


def test_constructor_compatibility_repair_upgrades_line_dash_length():
    source = """
from manim import GRAY, LEFT, Line, RIGHT, Scene

class Demo(Scene):
    def construct(self):
        proj_line = Line(LEFT, RIGHT, color=GRAY, dash_length=0.15)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        repaired = mutator.repair_source_compatibility()
        assert repaired is True
        assert mutator.save_atomic(scene_path) is True

        updated = scene_path.read_text(encoding="utf-8")
        lines = [line.strip() for line in updated.splitlines()]
        assert "from manim import GRAY, LEFT, Line, RIGHT, Scene, DashedLine" in lines
        assert "proj_line = DashedLine(LEFT, RIGHT, color=GRAY, dash_length=0.15)" in lines


def test_helper_return_property_persistence_is_blocked():
    source = """
from manim import *

class Demo(Scene):
    def make_label(self):
        return MathTex("x")

    def construct(self):
        label = self.make_label()
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        label_ref = next(
            (node for node in mutator.iter_scene_nodes() if node.node_kind == "helper_return"),
            None,
        )
        assert label_ref is not None
        strategy = mutator.plan_property_persistence(
            label_ref.variable_name,
            "color",
            source_key=label_ref.source_key,
        )
        assert strategy.no_persist is True
        assert "read-only" in strategy.reason or "source read-only" in strategy.reason


def test_position_persistence_requires_exact_source_anchor():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        group = VGroup(Circle(), Square())
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        group_ref = mutator.get_binding_by_name("group")
        assert group_ref is not None
        strategy = mutator.plan_position_persistence(
            "group",
            source_key=group_ref.source_key,
            path=(0,),
        )
        assert strategy.no_persist is True
        assert "exact source anchor" in strategy.reason


def test_named_property_safe_patch_injects_after_assignment():
    source = """
from manim import *

class Demo(Scene):
    def construct(self):
        circle = Circle()
        self.add(circle)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text(source, encoding="utf-8")

        mutator = ASTMutator()
        mutator.parse_file(scene_path)

        circle_ref = mutator.get_binding_by_name("circle")
        assert circle_ref is not None
        strategy = mutator.plan_property_persistence(
            "circle",
            "gloss",
            source_key=circle_ref.source_key,
        )
        assert strategy.safe_patch is True

        updated = mutator.update_property(
            "circle",
            "gloss",
            0.4,
            source_key=circle_ref.source_key,
        )
        assert updated is True
        assert mutator.save_atomic(scene_path) is True

        saved = scene_path.read_text(encoding="utf-8")
        assert "circle = Circle()" in saved
        assert "circle.set_gloss(0.4)" in saved


def test_code_editor_keeps_draft_when_shadow_build_fails():
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text("from manim import *\n", encoding="utf-8")

        watcher = DummyWatcher()
        editor = CodeEditorPanel(
            scene_file=str(scene_path),
            engine_state=DummyEngineState(),
            file_watcher=watcher,
        )
        editor.set_on_code_saved(
            lambda content: ShadowBuildResult(
                applied=False,
                status="Preview frozen — shadow build failed",
                error="shadow build failed",
            )
        )

        editor._editor.setPlainText("from manim import *\nclass Broken(")
        error = editor.flush_pending_save()
        assert error == "syntax_error"
        assert "Broken(" in editor._editor.toPlainText()

        scene_path.write_text("from manim import Scene\n", encoding="utf-8")
        editor.sync_from_file()
        assert "Broken(" in editor._editor.toPlainText()


def test_code_editor_applies_normalized_source_after_successful_shadow_commit():
    with tempfile.TemporaryDirectory() as tmpdir:
        scene_path = Path(tmpdir) / "scene.py"
        scene_path.write_text("from manim import *\n", encoding="utf-8")

        watcher = DummyWatcher()
        editor = CodeEditorPanel(
            scene_file=str(scene_path),
            engine_state=DummyEngineState(),
            file_watcher=watcher,
        )

        def apply_callback(content: str) -> ShadowBuildResult:
            normalized = content.rstrip() + "\n# normalized\n"
            scene_path.write_text(normalized, encoding="utf-8")
            return ShadowBuildResult(
                applied=True,
                status="Preview updated from code",
                applied_source=normalized,
            )

        editor.set_on_code_saved(apply_callback)
        editor._editor.setPlainText("from manim import *\n\nclass Demo(Scene):\n    pass\n")
        error = editor.flush_pending_save()
        assert error is None
        assert editor._editor.toPlainText().endswith("# normalized\n")

        scene_path.write_text("from manim import Scene\nclass External(Scene):\n    pass\n", encoding="utf-8")
        editor.sync_from_file()
        assert "class External(Scene)" in editor._editor.toPlainText()


def main() -> None:
    test_click_only_selection_is_safe()
    test_drag_below_threshold_stays_selection_only()
    test_drag_above_threshold_commits_once()
    test_property_value_equivalence_blocks_noop_persist()
    test_toolbar_sync_uses_live_animation_count()
    test_property_policy_prefers_correctness_for_geometry()
    test_drag_ast_injection_stays_after_assignment_and_modifiers()
    test_chained_assignment_uses_real_constructor_metadata()
    test_factory_method_assignment_is_not_misclassified_as_constructor()
    test_inline_constructor_creates_synthetic_source_node()
    test_helper_return_creates_read_only_source_node()
    test_non_mobject_assignments_are_filtered_out()
    test_group_children_create_inline_child_nodes()
    test_custom_mobject_subclass_is_detected()
    test_nested_live_readout_is_read_only_for_parent_backed_child_hits()
    test_exact_inline_child_live_readout_stays_editable()
    test_foreign_runtime_marker_does_not_fallback_by_line()
    test_owned_runtime_marker_without_exact_occurrence_stays_unmapped()
    test_selection_rebind_notifies_even_when_source_key_matches()
    test_constructor_compatibility_repair_upgrades_line_dash_length()
    test_helper_return_property_persistence_is_blocked()
    test_position_persistence_requires_exact_source_anchor()
    test_named_property_safe_patch_injects_after_assignment()
    test_code_editor_keeps_draft_when_shadow_build_fails()
    test_code_editor_applies_normalized_source_after_successful_shadow_commit()
    print("interaction safety tests passed")


if __name__ == "__main__":
    main()
