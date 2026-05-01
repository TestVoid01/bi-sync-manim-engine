"""
Slice 1–6 Automated Verification Tests
=======================================

Covers all 7 test cases from next plan.md Testing Strategy (lines 507-515):
1. renamed scene class loads
2. multiple scene classes deterministic discovery
3. inline constructor node in source graph
4. helper-return node read-only
5. factory-returned object source-backed params
6. transformed geometry prop reload-only
7. export correct scene name
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path
from types import SimpleNamespace

from engine.ast_mutator import ASTMutator, ASTParamRef, ASTValueRef
from engine.persistence_policy import PersistenceStrategy
from engine.property_policy import decide_property_application
from engine.scene_loader import (
    discover_scene_class_from_source,
    module_name_from_path,
)
from engine.state import EngineState


# ─────────────────────────────────────────────────────────────
# Test 1: Renamed scene class loads
# ─────────────────────────────────────────────────────────────

def test_renamed_scene_class_loads():
    """Scene class renamed from AdvancedScene → MyCustomScene still loads."""
    source = """\
from manim import *

class MyCustomScene(Scene):
    def construct(self):
        c = Circle(radius=1, color=BLUE)
        self.add(c)
"""
    cls = discover_scene_class_from_source(
        source,
        scene_file="test_scene.py",
        module_name="test_scene",
    )
    assert cls is not None, "Should discover renamed scene class"
    assert cls.__name__ == "MyCustomScene"


def test_renamed_scene_class_with_preferred_name():
    """preferred_name still works when class exists."""
    source = """\
from manim import *

class OriginalName(Scene):
    def construct(self):
        self.add(Circle())
"""
    cls = discover_scene_class_from_source(
        source,
        scene_file="test_scene.py",
        module_name="test_scene",
        preferred_name="OriginalName",
    )
    assert cls is not None
    assert cls.__name__ == "OriginalName"


def test_preferred_name_missing_still_discovers():
    """If preferred_name doesn't exist, fallback discovery works."""
    source = """\
from manim import *

class ActualScene(Scene):
    def construct(self):
        self.add(Square())
"""
    cls = discover_scene_class_from_source(
        source,
        scene_file="test_scene.py",
        module_name="test_scene",
        preferred_name="NonExistent",
    )
    assert cls is not None
    assert cls.__name__ == "ActualScene"


# ─────────────────────────────────────────────────────────────
# Test 2: Multiple scene classes → deterministic discovery
# ─────────────────────────────────────────────────────────────

def test_multiple_scene_classes_deterministic_pick():
    """With multiple Scene subclasses, discovery picks the last one deterministically."""
    source = """\
from manim import *

class SceneA(Scene):
    def construct(self):
        self.add(Circle())

class SceneB(Scene):
    def construct(self):
        self.add(Square())
"""
    cls = discover_scene_class_from_source(
        source,
        scene_file="test_scene.py",
        module_name="test_scene",
    )
    assert cls is not None
    assert cls.__name__ == "SceneB", "Should pick last scene class"


def test_multiple_scene_classes_preferred_overrides():
    """preferred_name overrides the default last-class pick."""
    source = """\
from manim import *

class SceneA(Scene):
    def construct(self):
        self.add(Circle())

class SceneB(Scene):
    def construct(self):
        self.add(Square())
"""
    cls = discover_scene_class_from_source(
        source,
        scene_file="test_scene.py",
        module_name="test_scene",
        preferred_name="SceneA",
    )
    assert cls is not None
    assert cls.__name__ == "SceneA"


# ─────────────────────────────────────────────────────────────
# Test 3: Inline constructor node appears in source graph
# ─────────────────────────────────────────────────────────────

def test_inline_constructor_in_self_add():
    """self.add(Circle(...)) creates an inline_direct source node."""
    source = """\
from manim import *

class Demo(Scene):
    def construct(self):
        self.add(Circle(radius=2, color=RED))
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "scene.py"
        p.write_text(source, encoding="utf-8")
        mutator = ASTMutator()
        mutator.parse_file(p)

        inline = [n for n in mutator.iter_scene_nodes() if n.node_kind == "inline_direct"]
        assert len(inline) >= 1, "Should find inline_direct node"
        assert inline[0].constructor_name == "Circle"
        assert inline[0].editability == "source_editable"


def test_inline_constructor_in_vgroup():
    """VGroup(Circle(), Square()) children create inline nodes."""
    source = """\
from manim import *

class Demo(Scene):
    def construct(self):
        group = VGroup(Circle(radius=2, color=RED), Square(side_length=1.5))
        self.add(group)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "scene.py"
        p.write_text(source, encoding="utf-8")
        mutator = ASTMutator()
        mutator.parse_file(p)

        group_ref = mutator.get_binding_by_name("group")
        assert group_ref is not None
        child0 = mutator.get_child_binding(group_ref.source_key, (0,))
        child1 = mutator.get_child_binding(group_ref.source_key, (1,))
        assert child0 is not None and child0.constructor_name == "Circle"
        assert child1 is not None and child1.constructor_name == "Square"


# ─────────────────────────────────────────────────────────────
# Test 4: Helper-return node is read-only
# ─────────────────────────────────────────────────────────────

def test_helper_return_is_read_only():
    """Objects from helper functions are source_read_only with a reason."""
    source = """\
from manim import *

def make_label():
    return MathTex("x").scale(2)

class Demo(Scene):
    def construct(self):
        label = make_label()
        self.add(label)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "scene.py"
        p.write_text(source, encoding="utf-8")
        mutator = ASTMutator()
        mutator.parse_file(p)

        helpers = [n for n in mutator.iter_scene_nodes() if n.node_kind == "helper_return"]
        assert len(helpers) >= 1, "Should find helper_return node"
        assert helpers[0].editability == "source_read_only"
        assert helpers[0].read_only_reason, "Should have a reason string"

        # Persistence should be no_persist
        strategy = mutator.plan_property_persistence(
            helpers[0].variable_name,
            "color",
            source_key=helpers[0].source_key,
        )
        assert strategy.no_persist, f"Helper return should be no_persist, got {strategy.mode}"


# ─────────────────────────────────────────────────────────────
# Test 5: Factory-returned object exposes source-backed params
# ─────────────────────────────────────────────────────────────

def test_factory_returned_object_has_source_params():
    """axes.plot(...) exposes x_range, color, stroke_width as source-backed params."""
    source = """\
from manim import *

class Demo(Scene):
    def construct(self):
        axes = Axes()
        curve = axes.plot(lambda x: x**2, x_range=[-2, 2], color=BLUE, stroke_width=7)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "scene.py"
        p.write_text(source, encoding="utf-8")
        mutator = ASTMutator()
        mutator.parse_file(p)

        curve = mutator.get_binding_by_name("curve")
        assert curve is not None
        assert curve.node_kind == "named_factory_method"
        assert curve.editability == "source_editable"

        param_names = {param.param_name for param in curve.constructor_params}
        assert "x_range" in param_names, f"Missing x_range in {param_names}"
        assert "color" in param_names, f"Missing color in {param_names}"
        assert "stroke_width" in param_names, f"Missing stroke_width in {param_names}"

        # Persistence should be exact_source for known params
        strategy = mutator.plan_property_persistence(
            "curve", "color", source_key=curve.source_key,
        )
        assert strategy.exact_source, f"Factory param should be exact_source, got {strategy.mode}"


# ─────────────────────────────────────────────────────────────
# Test 6: Transformed geometry prop is reload-only
# ─────────────────────────────────────────────────────────────

def test_transformed_geometry_prop_reload_only():
    """radius on a scaled Circle is reload_only with (base) label."""
    binding = SimpleNamespace(
        modifier_calls=[SimpleNamespace(owner_name="scale")],
    )
    decision = decide_property_application(
        "radius",
        widget_hint="slider",
        owner_kind="constructor",
        binding=binding,
    )
    assert decision.reload_only is True
    assert decision.live_safe is False
    assert "(base)" in decision.display_name


def test_live_geometry_readout_is_read_only():
    """Live width readout on a transformed object is read_only (effective)."""
    binding = SimpleNamespace(
        modifier_calls=[SimpleNamespace(owner_name="scale")],
    )
    decision = decide_property_application(
        "width",
        widget_hint="slider",
        owner_kind="live",
        binding=binding,
    )
    assert decision.read_only is True
    assert "(effective)" in decision.display_name


def test_visual_property_stays_live_safe_on_transformed():
    """color stays live_safe even on scaled objects."""
    binding = SimpleNamespace(
        modifier_calls=[SimpleNamespace(owner_name="scale")],
    )
    decision = decide_property_application(
        "color",
        widget_hint="color",
        owner_kind="constructor",
        binding=binding,
    )
    assert decision.live_safe is True


# ─────────────────────────────────────────────────────────────
# Test 7: Export uses correct (dynamic) scene name
# ─────────────────────────────────────────────────────────────

def test_export_scene_name_is_dynamic():
    """_resolve_active_scene_name uses live scene type, not hardcoded name."""
    # Simulate a live scene object
    class FancyScene:
        pass

    mock_canvas = SimpleNamespace(get_scene=lambda: FancyScene())
    mock_main = SimpleNamespace(canvas=mock_canvas)

    # Import the method reference
    from main import MainWindow
    result = MainWindow._resolve_active_scene_name(mock_main)
    assert result == "FancyScene", f"Expected 'FancyScene', got '{result}'"


def test_export_scene_name_fallback_uses_discovery():
    """When no live scene, falls back to discover_scene_class_from_file."""
    source = """\
from manim import *

class DynamicDemo(Scene):
    def construct(self):
        self.add(Circle())
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "scene.py"
        p.write_text(source, encoding="utf-8")

        from main import MainWindow
        mock_main = SimpleNamespace(
            canvas=SimpleNamespace(get_scene=lambda: None),
            _scene_path=str(p),
            _scene_module="scene",
            _preferred_scene_name=None,
        )
        result = MainWindow._resolve_active_scene_name(mock_main)
        assert result == "DynamicDemo", f"Expected 'DynamicDemo', got '{result}'"


# ─────────────────────────────────────────────────────────────
# Bonus: Persistence strategy tests (Slice 6 coverage)
# ─────────────────────────────────────────────────────────────

def test_persistence_exact_source_for_named_constructor():
    """Named constructor variable gets exact_source persistence."""
    source = """\
from manim import *

class Demo(Scene):
    def construct(self):
        circle = Circle(radius=1.5, color=BLUE)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "scene.py"
        p.write_text(source, encoding="utf-8")
        mutator = ASTMutator()
        mutator.parse_file(p)

        strategy = mutator.plan_property_persistence("circle", "radius")
        assert strategy.exact_source, f"Expected exact_source, got {strategy.mode}"


def test_persistence_no_persist_for_runtime_only():
    """Runtime-only objects get no_persist."""
    source = """\
from manim import *

class Demo(Scene):
    def construct(self):
        circle = Circle()
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "scene.py"
        p.write_text(source, encoding="utf-8")
        mutator = ASTMutator()
        mutator.parse_file(p)

        strategy = mutator.plan_property_persistence("__runtime_glyph_0", "color")
        assert strategy.no_persist, f"Expected no_persist, got {strategy.mode}"


def test_preview_drift_tracking():
    """EngineState tracks preview drift from no_persist edits."""
    state = EngineState()
    assert state.has_preview_drift is False

    state.record_preview_drift("circle position drag: runtime-only object")
    assert state.has_preview_drift is True
    assert "circle position drag" in state.preview_drift_summary

    state.clear_preview_drift()
    assert state.has_preview_drift is False
    assert state.preview_drift_summary == ""


def test_preview_drift_deduplication():
    """Same drift reason is not recorded twice."""
    state = EngineState()
    state.record_preview_drift("same reason")
    state.record_preview_drift("same reason")
    assert len(state._preview_drift_reasons) == 1


# ─────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import inspect
    import sys

    tests = [
        (name, obj)
        for name, obj in inspect.getmembers(sys.modules[__name__])
        if name.startswith("test_") and callable(obj)
    ]
    tests.sort(key=lambda t: t[0])

    passed = 0
    failed = 0
    errors = []

    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✅ {name}")
        except Exception as e:
            failed += 1
            errors.append((name, e))
            print(f"  ❌ {name}: {e}")

    print(f"\n{'='*60}")
    print(f"  {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'='*60}")

    if errors:
        print("\nFailed tests:")
        for name, e in errors:
            print(f"  • {name}: {e}")
        sys.exit(1)
