"""
Bi-Sync AST Mutator — Surgical Code Modification
==================================================

Phase 3: Bi-Directional Sync Bridge

Treats Python source code as a mathematical graph (AST) instead of
raw text. Surgically modifies specific property values in Manim
scene files without breaking formatting or structure.

The Flow:
    1. parse_file(path) → Loads .py into AST tree
    2. find_property(var, prop) → Locates exact AST node
    3. update_property(var, prop, val) → Edits node in-memory
    4. save_atomic(path) → tempfile+rename (no corruption)

Socket 4:
    register_live_bind(mobject_id, ast_ref) → O(1) lookup from
    rendered shape to its exact line in source code.

Safety:
    - All AST operations are in-memory (no eval/exec)
    - Atomic writes prevent file corruption
    - Original source preserved if AST unparse fails
"""

from __future__ import annotations

import ast
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from engine.persistence_policy import PersistenceStrategy

logger = logging.getLogger("bisync.ast_mutator")


@dataclass
class ASTAnimationRef:
    """Reference to an animation call in the AST.

    Phase 5: Used to map visual timeline keyframes back to code.
    """

    target_var: str
    method_name: str
    args: list[Any]
    line_number: int
    col_offset: int
    kwargs: dict[str, Any] = field(default_factory=dict)
    call_chain: list[Any] = field(default_factory=list)
    position_mode: str = "none"
    position_param_ref: Any = None
    stable_key: Optional[str] = None

    @property
    def animation_key(self) -> str:
        """Stable-ish key used by UI to rebind selected animation after reload."""
        if self.stable_key:
            return self.stable_key
        return f"{self.target_var}:{self.method_name}:{self.line_number}:{self.col_offset}"

    @property
    def is_draggable(self) -> bool:
        return self.position_mode in {"move_to", "shift", "effect_shift"} and self.position_param_ref is not None


@dataclass
class ASTValueRef:
    literal_value: Any = None
    raw_code: str = ""
    value_kind: str = "unknown"
    container_kind: Optional[str] = None


@dataclass(frozen=True)
class CodeExpression:
    """Exact Python expression payload used by code-backed property widgets."""

    raw_code: str


@dataclass
class ASTParamRef:
    target_var: str
    owner_kind: str
    owner_name: str
    line_number: int
    col_offset: int
    param_name: str
    param_index: Optional[int]
    value_ref: ASTValueRef

    @property
    def scoped_owner_name(self) -> str:
        """Compatibility label used by older property-panel code paths."""
        return self.owner_name


@dataclass
class ASTCallRef:
    target_var: str
    owner_kind: str
    owner_name: str
    line_number: int
    col_offset: int
    params: list[ASTParamRef] = field(default_factory=list)

    @property
    def scoped_owner_name(self) -> str:
        return self.owner_name


@dataclass
class ASTNodeRef:
    """Reference to a specific AST node's location in source code.

    Used by Socket 4 for O(1) mobject→code lookup.
    """

    variable_name: str
    line_number: int
    col_offset: int
    constructor_name: str  # e.g., "Circle", "Square"
    bisync_uuid: str = ""  # Persistent UUID injected during AST parsing
    properties: dict[str, Any] = field(default_factory=dict)
    transforms: dict[str, Any] = field(default_factory=dict) # To track .scale(), .rotate()
    source_key: Optional[str] = None
    editability: str = "source_editable"
    read_only_reason: str = ""
    display_name: str = ""
    inline_path: tuple[int, ...] = field(default_factory=tuple)
    constructor_params: list[ASTParamRef] = field(default_factory=list)
    modifier_calls: list[ASTCallRef] = field(default_factory=list)
    animation_calls: list[ASTCallRef] = field(default_factory=list)
    node_kind: str = "named_direct"
    primary_owner_kind: str = "constructor"
    parent_source_key: Optional[str] = None
    occurrence_index: int = 1


SceneNodeRef = ASTNodeRef


class PropertyFinder(ast.NodeVisitor):
    """Finds variable assignments with constructor calls and their properties.

    Scans the AST for patterns like:
        circle = Circle(radius=1.5, color=BLUE, fill_opacity=0.5)
        square = Square(side_length=2.0, color=RED)

    Builds a registry of {line_number: ASTNodeRef} for each found assignment.
    """

    def __init__(self, source: str = "", file_path: str | Path | None = None) -> None:
        self._source = source
        self._file_path = str(Path(file_path).resolve()) if file_path else None
        self.bindings: dict[int, ASTNodeRef] = {}
        self.scene_nodes: list[ASTNodeRef] = []
        self.bindings_by_name: dict[str, ASTNodeRef] = {}
        self.bindings_by_source_key: dict[str, ASTNodeRef] = {}
        self.child_bindings: dict[tuple[str, tuple[int, ...]], ASTNodeRef] = {}
        self.runtime_markers: dict[tuple[str, int, int], ASTNodeRef] = {}
        self.animations: list[ASTAnimationRef] = []
        self._custom_mobject_classes: set[str] = set()
        self._helper_returns: dict[str, str] = {}
        self._occurrence_by_line: dict[int, int] = {}
        self._imported_symbol_names: set[str] = set()
        self._manim_imported_names: set[str] = set()
        self._manim_star_imported: bool = False
        # Known Manim constructors we can modify
        self._known_constructors = {
            "Circle", "Square", "Triangle", "Dot", "Line", "DashedLine",
            "Rectangle", "Ellipse", "Arc", "Polygon", "RegularPolygon",
            "Text", "MathTex", "Tex", "MarkupText", "Paragraph",
            "Arrow", "Vector", "DoubleArrow", "CurvedArrow",
            "Axes", "NumberPlane", "ComplexPlane", "PolarPlane", "ThreeDAxes", "NumberLine",
            "ParametricFunction", "FunctionGraph", "ImplicitFunction",
            "VGroup", "Group", "Mobject", "VMobject",
            "ImageMobject", "SVGMobject", "Brace", "BraceLabel",
            "DecimalNumber", "Integer", "Matrix", "IntegerMatrix", "DecimalMatrix", "Table", "MathTable",
            "ValueTracker", "ComplexValueTracker",
            "Surface", "Sphere", "Cone", "Cylinder", "Cube", "Prism"
        }
        self._modifier_methods = {
            "move_to", "shift", "rotate", "scale", "stretch", "stretch_to_fit_height",
            "stretch_to_fit_width", "next_to", "to_edge", "to_corner", "align_to",
            "center", "flip", "arrange", "arrange_in_grid", "set", "set_x", "set_y",
            "set_z", "set_color", "set_fill", "set_stroke", "set_opacity",
            "set_fill_opacity", "set_stroke_opacity", "set_stroke_width",
            "set_width", "set_height", "set_depth", "set_gloss", "set_shadow",
            "set_sheen", "set_sheen_direction", "set_z_index", "match_width",
            "match_height", "match_color", "match_x", "match_y", "match_z",
            "match_style", "fade", "fade_to", "scale_to_fit_height",
            "scale_to_fit_width", "rescale_to_fit", "round_corners", "surround",
        }
        self._factory_product_overrides = {
            "plot": "ParametricFunction",
            "get_graph": "ParametricFunction",
            "get_area": "Polygon",
            "get_riemann_rectangles": "VGroup",
        }

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "manim":
                self._imported_symbol_names.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        is_manim_import = module == "manim" or module.startswith("manim.")
        for alias in node.names:
            imported_name = alias.asname or alias.name
            self._imported_symbol_names.add(imported_name)
            if is_manim_import:
                if alias.name == "*":
                    self._manim_star_imported = True
                else:
                    self._manim_imported_names.add(imported_name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            base_name = self._get_func_name(base)
            if base_name in {"Mobject", "VMobject", "OpenGLMobject", "OpenGLVMobject"}:
                self._custom_mobject_classes.add(node.name)
                self._known_constructors.add(node.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                helper_ref = self._node_from_expression(
                    target_name=f"__helper__{node.name}",
                    expr=child.value,
                    assign_node=child,
                    parent_source_key=None,
                    inline_path=(),
                )
                if helper_ref is not None:
                    self._helper_returns[node.name] = helper_ref.constructor_name
                    break
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit assignment nodes and build source-backed scene nodes."""
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            ref = self._node_from_expression(
                target_name=target_name,
                expr=node.value,
                assign_node=node,
                parent_source_key=None,
                inline_path=(),
            )
            if ref is not None:
                self._register_node(ref, top_level=True)
                self._register_inline_children(ref, node.value)

        self.generic_visit(node)
    def visit_Call(self, node: ast.Call) -> None:
        """Visit call nodes to find animations.

        Handles three patterns:
            1. self.play(obj.animate.method(...)) — e.g. circle.animate.shift(UP)
            2. self.play(Create(obj), FadeIn(obj), ...) — function-style animations
            3. self.wait(duration) — scene waits
        """
        func_name = self._get_func_name(node.func)

        if func_name == "play":
            # Extract kwargs from self.play(...)
            play_kwargs = {}
            for kw in node.keywords:
                if kw.arg is not None:
                    play_kwargs[kw.arg] = self._extract_value(kw.value)
                    
            # Pattern 1 & 2: self.play(...) with animation arguments
            for arg in node.args:
                self._extract_animation_from_play_arg(arg, play_kwargs)

        elif func_name == "wait":
            # Pattern 3: self.wait(duration)
            duration = 1.0
            if node.args and isinstance(node.args[0], (ast.Constant, ast.Name)):
                duration = self._extract_value(node.args[0]) or 1.0
                
            wait_kwargs = {}
            for kw in node.keywords:
                if kw.arg is not None:
                    wait_kwargs[kw.arg] = self._extract_value(kw.value)
                    
            ref = ASTAnimationRef(
                target_var="__scene__",
                method_name="wait",
                args=[duration],
                line_number=node.lineno,
                col_offset=node.col_offset,
                kwargs=wait_kwargs,
            )
            self.animations.append(ref)
            pass

        elif func_name == "add":
            for index, arg in enumerate(node.args):
                inline_ref = self._node_from_expression(
                    target_name=f"inline_{getattr(arg, 'lineno', node.lineno)}_{index}",
                    expr=arg,
                    assign_node=arg,
                    parent_source_key=None,
                    inline_path=(),
                )
                if inline_ref is not None:
                    inline_ref.node_kind = (
                        "inline_factory_method"
                        if inline_ref.primary_owner_kind == "factory_method"
                        else "inline_direct"
                    )
                    self._register_node(inline_ref, top_level=True)

        self.generic_visit(node)

    def _extract_animation_from_play_arg(self, arg: Any, play_kwargs: dict[str, Any]) -> None:
        """Extract animation from a single argument to self.play()."""
        # Pattern 1: obj.animate.method(...) — e.g. circle.animate.shift(UP)
        # Also handles chained methods e.g. circle.animate.set_color(RED).shift(UP)
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
            target_var, chain_calls = self._extract_animate_chain(arg)
            if target_var:
                position_call = next(
                    (call for call in chain_calls if self._get_func_name(call.func) in {"move_to", "shift"}),
                    None,
                )
                selected_call = position_call or arg
                method_name = self._get_func_name(selected_call.func)
                params = self._build_params(
                    target_var=target_var,
                    owner_kind="animation",
                    owner_name=method_name,
                    call_node=selected_call,
                )
                position_param = params[0] if position_call is not None and params else None
                position_mode = method_name if method_name in {"move_to", "shift"} else "none"
                call_chain = [
                    self._build_call_ref(
                        target_var=target_var,
                        owner_kind="animation",
                        owner_name=self._get_func_name(call.func),
                        call_node=call,
                    )
                    for call in chain_calls
                ]
                ref = ASTAnimationRef(
                    target_var=target_var,
                    method_name=method_name,
                    args=[self._extract_value(a) for a in selected_call.args],
                    line_number=selected_call.lineno,
                    col_offset=selected_call.col_offset,
                    kwargs=play_kwargs.copy(),
                    call_chain=call_chain,
                    position_mode=position_mode,
                    position_param_ref=position_param,
                )
                self.animations.append(ref)
                pass


                return

        # Pattern 2: Create(circle), FadeIn(circle), FadeOut(text), etc.
        # AST structure: Call(func=Name('Create'), args=[Name('circle')])
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
            func_name = arg.func.id
            if func_name in {
                "Create", "FadeIn", "FadeOut", "Grow", "Shrink",
                "Rotate", "Scale", "Write", "DrawBorderThenFill",
                "ReplacementTransform", "Transform", "FadeTransform",
                "SpinInFromNothing", "GrowFromCenter", "GrowArrow",
            }:
                # Extract target from first argument
                target = None
                if arg.args:
                    arg0 = arg.args[0]
                    # Simple name: Create(triangle)
                    if isinstance(arg0, ast.Name):
                        target = arg0.id
                    elif isinstance(arg0, ast.Call):
                        inline_ref = self._node_from_expression(
                            target_name=f"inline_play_{getattr(arg0, 'lineno', arg.lineno)}_0",
                            expr=arg0,
                            assign_node=arg0,
                            parent_source_key=None,
                            inline_path=(),
                        )
                        if inline_ref is not None:
                            inline_ref.node_kind = (
                                "inline_factory_method"
                                if inline_ref.primary_owner_kind == "factory_method"
                                else "inline_direct"
                            )
                            self._register_node(inline_ref, top_level=True)
                            target = inline_ref.variable_name
                    # Attribute: Create(self.triangle)
                    elif isinstance(arg0, ast.Attribute) and isinstance(arg0.value, ast.Name) and arg0.value.id == "self":
                        target = arg0.attr
                    # Nested attribute: Create(group[0])
                    elif isinstance(arg0, ast.Attribute):
                        target = getattr(arg0, 'attr', None)

                if target:
                    anim_kwargs = play_kwargs.copy()
                    effect_params = self._build_params(
                        target_var=target,
                        owner_kind="animation",
                        owner_name=func_name,
                        call_node=arg,
                    )
                    position_param = None
                    for kw in arg.keywords:
                        if kw.arg is not None:
                            anim_kwargs[kw.arg] = self._extract_value(kw.value)
                            if kw.arg == "shift":
                                position_param = next(
                                    (param for param in effect_params if param.param_name == "shift"),
                                    None,
                                )
                            
                    ref = ASTAnimationRef(
                        target_var=target,
                        method_name=func_name.lower(),  # convention: 'create' not 'Create'
                        args=[self._extract_value(a) for a in arg.args[1:]],
                        line_number=arg.lineno,
                        col_offset=arg.col_offset,
                        kwargs=anim_kwargs,
                        call_chain=[
                            ASTCallRef(
                                target_var=target,
                                owner_kind="animation",
                                owner_name=func_name,
                                line_number=arg.lineno,
                                col_offset=arg.col_offset,
                                params=effect_params,
                            )
                        ],
                        position_mode="effect_shift" if position_param is not None else "none",
                        position_param_ref=position_param,
                    )
                    self.animations.append(ref)
                    pass


    def _extract_animate_chain(self, call: ast.Call) -> tuple[Optional[str], list[ast.Call]]:
        chain: list[ast.Call] = []
        current: ast.AST = call
        target_var: Optional[str] = None
        while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
            chain.insert(0, current)
            owner = current.func.value
            if isinstance(owner, ast.Attribute) and owner.attr == "animate" and isinstance(owner.value, ast.Name):
                target_var = owner.value.id
                break
            current = owner
        return target_var, chain


    def visit_Expr(self, node: ast.Expr) -> None:
        """Scan for standalone or chained method calls like target.scale(1.5).set_color(RED)."""
        current = node.value
        while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
            method_name = current.func.attr
            
            # Find root target variable of this call chain
            root_target = current.func.value
            while isinstance(root_target, ast.Call) and isinstance(root_target.func, ast.Attribute):
                root_target = root_target.func.value
            
            if isinstance(root_target, ast.Name):
                target_var = root_target.id
                for ref in self.scene_nodes:
                    if ref.variable_name == target_var:
                        call_ref = self._build_call_ref(
                            target_var=target_var,
                            owner_kind="modifier",
                            owner_name=method_name,
                            call_node=current,
                        )
                        ref.modifier_calls.append(call_ref)
                        break
                if method_name in ("scale", "rotate"):
                    # Find the ASTNodeRef by variable name
                    for ref in self.scene_nodes:
                        if ref.variable_name == target_var:
                            if current.args:
                                val = self._extract_value(current.args[0])
                                ref.transforms[method_name] = val
                            break
                            
            # Move up the chain (which is down the AST tree)
            current = current.func.value
            
        self.generic_visit(node)

    def _get_func_name(self, node: ast.expr) -> str:
        """Extract function name from Call node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""

    def _register_node(self, ref: ASTNodeRef, *, top_level: bool) -> None:
        self.scene_nodes.append(ref)
        self.bindings_by_source_key[ref.source_key or ""] = ref
        if ref.source_key:
            self.child_bindings[(ref.source_key, tuple(ref.inline_path))] = ref
        if ref.parent_source_key:
            self.child_bindings[(ref.parent_source_key, tuple(ref.inline_path))] = ref
        if ref.variable_name:
            self.bindings_by_name[ref.variable_name] = ref
        if top_level:
            self.bindings.setdefault(ref.line_number, ref)
        if self._file_path:
            self.runtime_markers[(self._file_path, ref.line_number, ref.occurrence_index)] = ref

    def _next_occurrence(self, line_number: int) -> int:
        self._occurrence_by_line[line_number] = self._occurrence_by_line.get(line_number, 0) + 1
        return self._occurrence_by_line[line_number]

    def _source_key(self, target_name: str, line: int, col: int, kind: str, occurrence: int, path: tuple[int, ...] = ()) -> str:
        path_part = ".".join(str(i) for i in path) if path else "root"
        return f"{target_name}:{line}:{col}:{kind}:{occurrence}:{path_part}"

    def _node_from_expression(
        self,
        *,
        target_name: str,
        expr: ast.AST,
        assign_node: ast.AST,
        parent_source_key: Optional[str],
        inline_path: tuple[int, ...],
    ) -> Optional[ASTNodeRef]:
        if not isinstance(expr, ast.Call):
            return None

        classification = self._classify_scene_expression(expr)
        if classification is None:
            return None
        primary_call = classification["primary_call"]
        primary_owner_kind = classification["primary_owner_kind"]
        constructor_name = classification["constructor_name"]
        node_kind = classification["node_kind"]
        editability = classification["editability"]
        read_only_reason = classification["read_only_reason"]
        primary_name = classification["primary_name"]
        modifier_chain = classification["modifier_chain"]

        if inline_path:
            node_kind = (
                "inline_factory_method"
                if primary_owner_kind == "factory_method"
                else "inline_direct"
            )

        occurrence = self._next_occurrence(getattr(primary_call, "lineno", getattr(assign_node, "lineno", 0)))
        source_key = self._source_key(
            target_name,
            getattr(primary_call, "lineno", getattr(assign_node, "lineno", 0)),
            getattr(primary_call, "col_offset", getattr(assign_node, "col_offset", 0)),
            node_kind,
            occurrence,
            inline_path,
        )
        params = self._build_params(
            target_var=target_name,
            owner_kind=primary_owner_kind,
            owner_name=primary_name,
            call_node=primary_call,
        )
        props = {param.param_name: param.value_ref.literal_value for param in params if param.param_name}

        ref = ASTNodeRef(
            variable_name=target_name,
            line_number=getattr(primary_call, "lineno", getattr(assign_node, "lineno", 0)),
            col_offset=getattr(primary_call, "col_offset", getattr(assign_node, "col_offset", 0)),
            constructor_name=constructor_name,
            bisync_uuid=target_name,
            properties=props,
            source_key=source_key,
            editability=editability,
            read_only_reason=read_only_reason,
            display_name=target_name,
            inline_path=inline_path,
            constructor_params=params,
            node_kind=node_kind,
            primary_owner_kind=primary_owner_kind,
            parent_source_key=parent_source_key,
            occurrence_index=occurrence,
        )
        for call in modifier_chain:
            ref.modifier_calls.append(
                self._build_call_ref(
                    target_var=target_name,
                    owner_kind="modifier",
                    owner_name=self._get_func_name(call.func),
                    call_node=call,
                )
            )
        return ref

    def _classify_scene_expression(self, expr: ast.Call) -> Optional[dict[str, Any]]:
        root_call, modifier_chain = self._split_call_chain(expr)
        if root_call is None:
            return None

        factory_match = self._find_factory_call(root_call, modifier_chain)
        if factory_match is not None:
            factory_call, post_factory_chain = factory_match
            method_name = self._get_func_name(factory_call.func)
            return {
                "primary_call": factory_call,
                "primary_owner_kind": "factory_method",
                "constructor_name": self._factory_product_name(method_name),
                "node_kind": "named_factory_method",
                "editability": "source_editable",
                "read_only_reason": "",
                "primary_name": method_name,
                "modifier_chain": post_factory_chain,
            }

        if isinstance(root_call.func, ast.Name):
            func_name = self._get_func_name(root_call.func)
            if func_name in self._helper_returns:
                return {
                    "primary_call": root_call,
                    "primary_owner_kind": "helper_return",
                    "constructor_name": self._helper_returns[func_name],
                    "node_kind": "helper_return",
                    "editability": "source_read_only",
                    "read_only_reason": "helper-return objects are source read-only in v1",
                    "primary_name": func_name,
                    "modifier_chain": modifier_chain,
                }
            if self._is_probable_scene_constructor_name(func_name):
                return {
                    "primary_call": root_call,
                    "primary_owner_kind": "constructor",
                    "constructor_name": func_name,
                    "node_kind": "named_chained" if modifier_chain else "named_direct",
                    "editability": "source_editable",
                    "read_only_reason": "",
                    "primary_name": func_name,
                    "modifier_chain": modifier_chain,
                }
        elif (
            isinstance(root_call.func, ast.Attribute)
            and isinstance(root_call.func.value, ast.Name)
            and root_call.func.value.id == "self"
        ):
            helper_name = root_call.func.attr
            if helper_name in self._helper_returns:
                return {
                    "primary_call": root_call,
                    "primary_owner_kind": "helper_return",
                    "constructor_name": self._helper_returns[helper_name],
                    "node_kind": "helper_return",
                    "editability": "source_read_only",
                    "read_only_reason": "helper-return objects are source read-only in v1",
                    "primary_name": helper_name,
                    "modifier_chain": modifier_chain,
                }
        return None

    def _find_factory_call(
        self,
        root_call: ast.Call,
        modifier_chain: list[ast.Call],
    ) -> Optional[tuple[ast.Call, list[ast.Call]]]:
        chain_calls: list[ast.Call] = []
        if isinstance(root_call.func, ast.Attribute):
            chain_calls.append(root_call)
        chain_calls.extend(modifier_chain)

        for index, call in enumerate(chain_calls):
            if not isinstance(call.func, ast.Attribute):
                continue
            method_name = call.func.attr
            if method_name in self._modifier_methods:
                continue
            if not self._expression_returns_scene_object(call.func.value):
                continue
            return call, chain_calls[index + 1:]
        return None

    def _expression_returns_scene_object(self, expr: ast.AST) -> bool:
        if isinstance(expr, ast.Name):
            return expr.id in self.bindings_by_name or expr.id in self._helper_returns
        if isinstance(expr, ast.Subscript):
            return self._expression_returns_scene_object(expr.value)
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            if expr.value.id == "self":
                return True
        if isinstance(expr, ast.Call):
            return self._classify_scene_expression(expr) is not None
        return False

    def _is_probable_scene_constructor_name(self, func_name: str) -> bool:
        if not func_name:
            return False
        if func_name in self._known_constructors:
            return True
        if func_name in self._custom_mobject_classes:
            return True
        if func_name in self._manim_imported_names:
            return True
        if func_name in self._imported_symbol_names and func_name[:1].isupper():
            return True
        if self._manim_star_imported and func_name[:1].isupper():
            return True
        return False

    def _factory_product_name(self, method_name: str) -> str:
        if method_name in self._factory_product_overrides:
            return self._factory_product_overrides[method_name]
        return method_name

    def _register_inline_children(self, parent_ref: ASTNodeRef, expr: ast.AST) -> None:
        root_call, _chain = self._split_call_chain(expr)
        if root_call is None:
            return
        for index, arg in enumerate(root_call.args):
            child = self._node_from_expression(
                target_name=f"{parent_ref.variable_name}[{index}]",
                expr=arg,
                assign_node=arg,
                parent_source_key=parent_ref.source_key,
                inline_path=(index,),
            )
            if child is not None:
                self._register_node(child, top_level=False)

    def _split_call_chain(self, expr: ast.AST) -> tuple[Optional[ast.Call], list[ast.Call]]:
        if not isinstance(expr, ast.Call):
            return None, []
        chain: list[ast.Call] = []
        current = expr
        while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
            owner = current.func.value
            if isinstance(owner, ast.Call):
                chain.insert(0, current)
                current = owner
                continue
            break
        if isinstance(current, ast.Call):
            return current, chain
        return None, chain

    def _build_call_ref(self, target_var: str, owner_kind: str, owner_name: str, call_node: ast.Call) -> ASTCallRef:
        return ASTCallRef(
            target_var=target_var,
            owner_kind=owner_kind,
            owner_name=owner_name,
            line_number=getattr(call_node, "lineno", 0),
            col_offset=getattr(call_node, "col_offset", 0),
            params=self._build_params(
                target_var=target_var,
                owner_kind=owner_kind,
                owner_name=owner_name,
                call_node=call_node,
            ),
        )

    def _build_params(self, target_var: str, owner_kind: str, owner_name: str, call_node: ast.Call) -> list[ASTParamRef]:
        params: list[ASTParamRef] = []
        positional_names = self._positional_names(owner_name, call_node, owner_kind)
        for index, arg in enumerate(call_node.args):
            name = positional_names[index] if index < len(positional_names) else f"arg{index}"
            params.append(ASTParamRef(
                target_var=target_var,
                owner_kind=owner_kind,
                owner_name=owner_name,
                line_number=getattr(arg, "lineno", getattr(call_node, "lineno", 0)),
                col_offset=getattr(arg, "col_offset", getattr(call_node, "col_offset", 0)),
                param_name=name,
                param_index=index,
                value_ref=self._build_value_ref(arg),
            ))
        for kw in call_node.keywords:
            if kw.arg is None:
                continue
            params.append(ASTParamRef(
                target_var=target_var,
                owner_kind=owner_kind,
                owner_name=owner_name,
                line_number=getattr(kw.value, "lineno", getattr(call_node, "lineno", 0)),
                col_offset=getattr(kw.value, "col_offset", getattr(call_node, "col_offset", 0)),
                param_name=kw.arg,
                param_index=None,
                value_ref=self._build_value_ref(kw.value),
            ))
        return params

    def _positional_names(self, owner_name: str, call_node: ast.Call, owner_kind: str) -> list[str]:
        if owner_name in {"Text", "Tex", "MathTex"}:
            return ["text"]
        if owner_name == "Dot":
            return ["point"]
        if owner_name in {"Line", "Arrow", "DoubleArrow", "DashedLine"}:
            return ["start", "end"]
        if owner_name == "next_to":
            return ["mobject_or_point", "direction"]
        if owner_name == "to_edge":
            return ["edge"]
        if owner_name in {"move_to", "shift"}:
            return ["point" if owner_name == "move_to" else "vector"]
        if owner_name == "plot" and owner_kind == "factory_method":
            return ["function"]
        return [f"arg{i}" for i, _ in enumerate(call_node.args)]

    def _build_value_ref(self, node: ast.expr) -> ASTValueRef:
        literal = self._extract_value(node)
        raw_code = ast.get_source_segment(self._source, node) if self._source else None
        if raw_code is None:
            try:
                raw_code = ast.unparse(node)
            except Exception:
                raw_code = ""
        container_kind = None
        if isinstance(node, ast.List):
            container_kind = "list"
        elif isinstance(node, ast.Tuple):
            container_kind = "tuple"
        if isinstance(literal, bool):
            value_kind = "bool"
        elif isinstance(literal, (int, float)):
            value_kind = "number"
        elif isinstance(literal, str):
            value_kind = "string"
        elif isinstance(literal, list):
            value_kind = "container"
        elif literal is None:
            value_kind = "expression"
        else:
            value_kind = type(literal).__name__
        return ASTValueRef(
            literal_value=literal,
            raw_code=raw_code,
            value_kind=value_kind,
            container_kind=container_kind,
        )

    def _extract_value(self, node: ast.expr) -> Any:
        """Extract Python value from AST node."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return node.id  # Return name as string (e.g., BLUE, RED)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            val = self._extract_value(node.operand)
            if isinstance(val, (int, float)):
                return -val
        # Handle lists/tuples/arrays (e.g. for [1, 2, 0])
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self._extract_value(e) for e in node.elts]
        return None  # Complex expressions we can't easily extract


class PropertyUpdater(ast.NodeTransformer):
    """Surgically modifies a specific property in an AST constructor call.

    Given: target_var="circle", prop_name="radius", new_value=3.0
    Transforms:
        circle = Circle(radius=1.5, color=BLUE)
    Into:
        circle = Circle(radius=3.0, color=BLUE)

    Only modifies the EXACT node — all other code is untouched.
    """

    def __init__(
        self,
        target_var: str,
        prop_name: str,
        new_value: Any,
    ) -> None:
        self._target_var = target_var
        self._prop_name = prop_name
        self._new_value = new_value
        self._modified = False
        self._was_skipped = False

    def _build_expr(self) -> Optional[ast.expr]:
        value = self._new_value
        if isinstance(value, CodeExpression):
            try:
                return ast.parse(value.raw_code, mode="eval").body
            except SyntaxError as exc:
                logger.warning(
                    "Invalid code expression for %s.%s: %s",
                    self._target_var,
                    self._prop_name,
                    exc,
                )
                self._was_skipped = True
                return None
        if isinstance(value, bool) or value is None or isinstance(value, (int, float, str)):
            return ast.Constant(value=value)
        if isinstance(value, list):
            return ast.List(
                elts=[PropertyUpdater._expr_from_literal(item) for item in value],
                ctx=ast.Load(),
            )
        if isinstance(value, tuple):
            return ast.Tuple(
                elts=[PropertyUpdater._expr_from_literal(item) for item in value],
                ctx=ast.Load(),
            )
        return ast.Constant(value=str(value))

    @staticmethod
    def _expr_from_literal(value: Any) -> ast.expr:
        if isinstance(value, bool) or value is None or isinstance(value, (int, float, str)):
            return ast.Constant(value=value)
        if isinstance(value, list):
            return ast.List(
                elts=[PropertyUpdater._expr_from_literal(item) for item in value],
                ctx=ast.Load(),
            )
        if isinstance(value, tuple):
            return ast.Tuple(
                elts=[PropertyUpdater._expr_from_literal(item) for item in value],
                ctx=ast.Load(),
            )
        return ast.Constant(value=str(value))

    @property
    def was_modified(self) -> bool:
        return self._modified
        
    @property
    def was_skipped(self) -> bool:
        return self._was_skipped

    def visit_Assign(self, node: ast.Assign) -> ast.Assign:
        """Find the target assignment and modify its property."""
        replacement_expr = self._build_expr()
        if replacement_expr is None and self._was_skipped:
            return node

        is_target = False
        if len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == self._target_var:
                is_target = True
            elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self" and target.attr == self._target_var:
                is_target = True

        if is_target and isinstance(node.value, ast.Call):
            # Special case for "text" property in Text/Tex (first positional arg)
            if self._prop_name == "text" and node.value.args:
                node.value.args[0] = replacement_expr
                self._modified = True
                logger.info(
                    f"AST Surgery: {self._target_var}.text "
                    f"→ {self._new_value} (line {node.lineno})"
                )
                return node
                
            # Found the target assignment — modify the keyword
            for kw in node.value.keywords:
                if kw.arg == self._prop_name:
                    if isinstance(kw.value, ast.Constant):
                        # Safe to replace — it's a simple literal
                        kw.value = replacement_expr
                        self._modified = True
                        logger.info(
                            f"AST Surgery: {self._target_var}.{self._prop_name} "
                            f"→ {self._new_value} (line {node.lineno})"
                        )
                    elif isinstance(kw.value, ast.IfExp) and getattr(kw.value.test, "value", False) is True:
                        # Already wrapped, update the body
                        kw.value.body = replacement_expr
                        self._modified = True
                        logger.info(
                            f"AST Surgery: Updated wrapped {self._target_var}.{self._prop_name} "
                            f"→ {self._new_value} (line {node.lineno})"
                        )
                    else:
                        # Complex expression — wrap it instead of losing it!
                        # e.g., `radius=3.5 if True else (UP*2)`
                        kw.value = ast.IfExp(
                            test=ast.Constant(value=True),
                            body=replacement_expr,
                            orelse=kw.value
                        )
                        self._modified = True
                        logger.info(
                            f"AST Surgery: Wrapped {self._target_var}.{self._prop_name} "
                            f"→ {self._new_value} (line {node.lineno})"
                        )
                    break
            else:
                # Property doesn't exist yet — add it as new keyword
                new_kw = ast.keyword(
                    arg=self._prop_name,
                    value=replacement_expr,
                )
                node.value.keywords.append(new_kw)
                self._modified = True
                logger.info(
                    f"AST Surgery: Added {self._target_var}.{self._prop_name} "
                    f"= {self._new_value} (line {node.lineno})"
                )

        return node


class ASTMutator:
    """Main AST mutation engine for the Bi-Sync system.

    Provides the complete pipeline:
        parse → find → modify → save (atomic)

    Thread Safety:
        NOT thread-safe. All calls must come from the Qt main thread.
        This is guaranteed because PyQt signals are main-thread by default.
    """

    def __init__(self) -> None:
        self._tree: Optional[ast.Module] = None
        self._source: Optional[str] = None
        self._file_path: Optional[Path] = None
        # Primary index: line_number → ASTNodeRef
        self._bindings: dict[int, ASTNodeRef] = {}
        # Secondary index: variable_name → ASTNodeRef (O(1) lookup)
        self._bindings_by_name: dict[str, ASTNodeRef] = {}
        self._scene_nodes: list[ASTNodeRef] = []
        self._bindings_by_source_key: dict[str, ASTNodeRef] = {}
        self._child_bindings: dict[tuple[str, tuple[int, ...]], ASTNodeRef] = {}
        self._runtime_markers: dict[tuple[str, int, int], ASTNodeRef] = {}
        self._animations: list[ASTAnimationRef] = []

        # Socket 4: Live binds — mobject_id → ASTNodeRef
        self._live_binds: dict[int, ASTNodeRef] = {}
        self.last_error: Optional[str] = None

        logger.info("ASTMutator initialized")

    @property
    def bindings(self) -> dict[int, ASTNodeRef]:
        """Return current line_number→AST bindings."""
        return self._bindings

    def get_binding_by_name(self, var_name: str) -> Optional[ASTNodeRef]:
        """O(1) lookup by variable name. Use instead of linear search."""
        return self._bindings_by_name.get(var_name)

    @property
    def animations(self) -> list[ASTAnimationRef]:
        """Return current parsed animations."""
        return self._animations

    @property
    def rendered_source(self) -> str:
        """Return current source-of-truth text for commit checks."""
        if self._tree is not None:
            try:
                return self._generate_format_preserving_source()
            except Exception:
                pass
        return (self._source or "")

    @property
    def is_dirty(self) -> bool:
        """Compatibility flag for callers expecting dirty-state tracking."""
        if self._tree is None:
            return False
        try:
            return (self._source or "").rstrip() != self._generate_format_preserving_source().rstrip()
        except Exception:
            return False

    def parse_file(self, path: str | Path) -> dict[int, ASTNodeRef]:
        """Parse a Python file and extract all Manim variable bindings.

        Args:
            path: Path to the .py scene file

        Returns:
            dict of variable_name → ASTNodeRef for all Manim constructors found
        """
        path = Path(path)
        self._file_path = path

        self._source = path.read_text(encoding="utf-8")
        self._tree = ast.parse(self._source, filename=str(path))

        # Find all Manim variable bindings
        finder = PropertyFinder(self._source, path)
        finder.visit(self._tree)
        self._bindings = finder.bindings
        # Build O(1) name index
        self._bindings_by_name = finder.bindings_by_name
        self._scene_nodes = finder.scene_nodes
        self._bindings_by_source_key = finder.bindings_by_source_key
        self._child_bindings = finder.child_bindings
        self._runtime_markers = finder.runtime_markers
        self._animations = finder.animations

        logger.info(
            f"Parsed {path.name}: {len(self._bindings)} bindings found "
            f"({', '.join(str(k) for k in self._bindings.keys())})"
        )
        logger.info(f"Parsed {path.name}: {len(self._animations)} animations found")
        return self._bindings

    def parse_source_text(self, path: str | Path, source_text: str) -> dict[int, ASTNodeRef]:
        """Parse source directly (used by shadow validation flow)."""
        path = Path(path)
        self._file_path = path
        self._source = source_text
        self._tree = ast.parse(source_text, filename=str(path))
        finder = PropertyFinder(source_text, path)
        finder.visit(self._tree)
        self._bindings = finder.bindings
        self._bindings_by_name = finder.bindings_by_name
        self._scene_nodes = finder.scene_nodes
        self._bindings_by_source_key = finder.bindings_by_source_key
        self._child_bindings = finder.child_bindings
        self._runtime_markers = finder.runtime_markers
        self._animations = finder.animations
        return self._bindings

    def iter_scene_nodes(self):
        """Compatibility iterator expected by MainWindow snapshot flow."""
        return self._scene_nodes

    def get_binding_by_source_key(self, source_key: Optional[str]):
        if not source_key:
            return None
        return self._bindings_by_source_key.get(source_key)

    def get_binding_by_line(self, line_number: int) -> Optional[ASTNodeRef]:
        return self._bindings.get(line_number)

    def get_binding_by_runtime_marker(
        self,
        source_file: Optional[str],
        line_number: Optional[int],
        occurrence: Optional[int],
    ) -> Optional[ASTNodeRef]:
        if line_number is None:
            return None
        if source_file:
            if not self.owns_source_file(source_file):
                return None
            try:
                resolved = str(Path(source_file).resolve())
            except Exception:
                resolved = source_file
            if occurrence is not None:
                return self._runtime_markers.get((resolved, line_number, occurrence))
            return None
        return self._bindings.get(line_number)

    def get_child_binding(self, source_key: Optional[str], path: tuple[int, ...]):
        if not source_key:
            return None
        return self._child_bindings.get((source_key, tuple(path)))

    def owns_source_file(self, source_file: Optional[str]) -> bool:
        if self._file_path is None or not source_file:
            return False
        try:
            return str(Path(source_file).resolve()) == str(self._file_path.resolve())
        except Exception:
            return False

    def clear_live_binds(self) -> None:
        self._live_binds.clear()

    def get_animation_by_key(self, animation_key: Optional[str]) -> Optional[ASTAnimationRef]:
        if animation_key is None:
            return None
        for anim in self._animations:
            if anim.animation_key == animation_key:
                return anim
        parts = animation_key.split(":")
        if len(parts) >= 2:
            target, method = parts[0], parts[1]
            for anim in self._animations:
                if anim.target_var == target and anim.method_name == method:
                    anim.stable_key = animation_key
                    return anim
        return None

    def _rebuild_metadata_from_tree(self) -> None:
        if self._tree is None:
            return
        source_for_segments = self._source or ast.unparse(self._tree)
        finder = PropertyFinder(source_for_segments, self._file_path)
        finder.visit(self._tree)
        self._bindings = finder.bindings
        self._bindings_by_name = finder.bindings_by_name
        self._scene_nodes = finder.scene_nodes
        self._bindings_by_source_key = finder.bindings_by_source_key
        self._child_bindings = finder.child_bindings
        self._runtime_markers = finder.runtime_markers
        self._animations = finder.animations

    def plan_property_persistence(
        self,
        target_var: str,
        prop_name: str,
        *,
        source_key: Optional[str] = None,
        path: tuple[int, ...] = (),
    ) -> PersistenceStrategy:
        """Choose persistence mode for an edit (exact/patch/no-persist)."""
        if source_key:
            ref = self.get_binding_by_source_key(source_key)
            if ref is not None:
                if ref.editability != "source_editable":
                    return PersistenceStrategy(
                        mode="no_persist",
                        reason=ref.read_only_reason or "source read-only target",
                        source_key=source_key,
                    )
                if path and tuple(path) != tuple(getattr(ref, "inline_path", ())):
                    return PersistenceStrategy(
                        mode="no_persist",
                        reason="selected runtime child is not an exact source anchor",
                        source_key=source_key,
                    )
                if prop_name in ref.properties or prop_name in {"text"}:
                    return PersistenceStrategy(
                        mode="exact_source",
                        reason="source key resolves to canonical AST binding",
                        source_key=source_key,
                    )
                return PersistenceStrategy(
                    mode="safe_patch",
                    reason="property is not a constructor param; use post-creation patch",
                    source_key=source_key,
                )

        ref_by_name = self.get_binding_by_name(target_var)
        if ref_by_name is not None:
            return PersistenceStrategy(
                mode="exact_source",
                reason="variable name resolves to canonical AST binding",
                source_key=getattr(ref_by_name, "source_key", None),
            )

        if target_var.startswith("__runtime_"):
            return PersistenceStrategy(
                mode="no_persist",
                reason="runtime-only object has no reliable source anchor",
                source_key=source_key,
            )

        return PersistenceStrategy(
            mode="safe_patch",
            reason="fallback patch may be possible if post-creation anchor exists",
            source_key=source_key,
        )

    def plan_position_persistence(
        self,
        target_var: str,
        *,
        source_key: Optional[str] = None,
        path: tuple[int, ...] = (),
    ) -> PersistenceStrategy:
        """Choose persistence mode for drag-position edits."""
        if source_key:
            ref = self.get_binding_by_source_key(source_key)
            if ref is None:
                return PersistenceStrategy("no_persist", "source anchor could not be resolved", source_key)
            if ref.editability != "source_editable":
                return PersistenceStrategy("no_persist", ref.read_only_reason or "source read-only target", source_key)
            if tuple(path) != tuple(getattr(ref, "inline_path", ())):
                return PersistenceStrategy("no_persist", "selected runtime child is not an exact source anchor", source_key)
            return PersistenceStrategy("safe_patch", "position persists as post-creation move_to patch", source_key)
        ref = self.get_binding_by_name(target_var)
        if ref is not None and ref.editability == "source_editable":
            return PersistenceStrategy("safe_patch", "variable name resolves to source-backed object", ref.source_key)
        return PersistenceStrategy("no_persist", "runtime-only object has no reliable source anchor", source_key)

    def persist_property_edit(
        self,
        target_var: str,
        prop_name: str,
        new_value: Any,
        strategy: PersistenceStrategy,
    ) -> bool:
        """Persist one property edit according to the chosen strategy."""
        if strategy.no_persist:
            return False

        # Idempotence check
        ref = self.get_binding_by_name(target_var)
        if ref and prop_name in ref.properties:
            if ref.properties[prop_name] == new_value:
                return True

        if strategy.exact_source:
            return self.update_property(target_var, prop_name, new_value, source_key=strategy.source_key)

        # safe_patch fallback
        return self._inject_post_creation_assignment(target_var, prop_name, new_value)

    def _inject_post_creation_assignment(
        self,
        target_var: str,
        prop_name: str,
        new_value: Any,
    ) -> bool:
        """Inject a post-creation fallback patch for hard-to-map edits."""
        if self._tree is None:
            logger.error("No file parsed yet. Call parse_file() first.")
            return False

        current_value = self.read_property(target_var, prop_name)
        if current_value == new_value:
            return True

        if self._file_path:
            try:
                self.parse_file(self._file_path)
            except Exception as e:
                logger.error(f"Failed to re-parse before injection: {e}")
                return False

        ref = self.get_binding_by_name(target_var)
        if ref is None:
            logger.warning("Safe patch failed: no binding for %s", target_var)
            return False

        class AssignmentInjector(ast.NodeTransformer):
            def __init__(self, target: str, prop: str, value: Any, line: int) -> None:
                self.target = target
                self.prop = prop
                self.value = value
                self.line = line
                self.injected = False

            def _target_expr(self) -> ast.Name:
                return ast.Name(id=self.target, ctx=ast.Load())

            def _literal(self) -> ast.expr:
                if isinstance(self.value, CodeExpression):
                    return ast.parse(self.value.raw_code, mode="eval").body
                if isinstance(self.value, (int, float, str, bool)) or self.value is None:
                    return ast.Constant(value=self.value)
                if isinstance(self.value, list):
                    return ast.List(
                        elts=[PropertyUpdater._expr_from_literal(v) for v in self.value],
                        ctx=ast.Load(),
                    )
                if isinstance(self.value, tuple):
                    return ast.Tuple(
                        elts=[PropertyUpdater._expr_from_literal(v) for v in self.value],
                        ctx=ast.Load(),
                    )
                return ast.Constant(value=str(self.value))

            def _call_stmt(self, method_name: str, *args: ast.expr, **kwargs: ast.expr) -> ast.Expr:
                return ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=self._target_expr(),
                            attr=method_name,
                            ctx=ast.Load(),
                        ),
                        args=list(args),
                        keywords=[ast.keyword(arg=k, value=v) for k, v in kwargs.items()],
                    )
                )

            def _patch_stmt(self) -> ast.stmt:
                p = self.prop.lower()
                lit = self._literal()

                # Color + opacity semantics
                if p == "color":
                    return self._call_stmt("set_color", lit)
                if p == "fill_opacity":
                    return self._call_stmt("set_fill", opacity=lit)
                if p == "stroke_width":
                    return self._call_stmt("set_stroke", width=lit)
                if p == "stroke_opacity":
                    return self._call_stmt("set_stroke", opacity=lit)
                if p.endswith("_color"):
                    return self._call_stmt(
                        "set_style",
                        **{p: lit},
                    )

                # Geometry-like transforms
                if p in {"width", "height"}:
                    return self._call_stmt(f"set_{p}", lit)
                if p in {"x", "y", "z"}:
                    axis_idx = {"x": 0, "y": 1, "z": 2}[p]
                    return self._call_stmt("set_coord", lit, ast.Constant(value=axis_idx))
                if p in {"move_to", "position", "center"} and isinstance(self.value, (list, tuple)):
                    return self._call_stmt("move_to", lit)

                if p == "gloss":
                    return self._call_stmt("set_gloss", lit)

                # Fallback: direct assignment
                return ast.Assign(
                    targets=[
                        ast.Attribute(
                            value=self._target_expr(),
                            attr=self.prop,
                            ctx=ast.Store(),
                        )
                    ],
                    value=lit,
                )

            def _inject_into_stmt_list(self, stmts: list[ast.stmt]) -> list[ast.stmt]:
                output: list[ast.stmt] = []
                p = self.prop.lower()
                
                # Semantic mapping of property to Manim setter methods
                setter_map = {
                    "color": "set_color",
                    "fill_opacity": "set_fill",
                    "stroke_width": "set_stroke",
                    "stroke_opacity": "set_stroke",
                }
                target_setter = setter_map.get(p)
                
                for stmt in stmts:
                    # Check if this is an existing call to a setter for this property
                    is_existing_setter = False
                    if (not self.injected and target_setter and 
                        isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and
                        isinstance(stmt.value.func, ast.Attribute) and 
                        isinstance(stmt.value.func.value, ast.Name) and 
                        stmt.value.func.value.id == self.target and
                        stmt.value.func.attr == target_setter):
                        
                        # We found a potential setter. Check if it's the RIGHT one for stroke_width vs stroke_opacity
                        if target_setter == "set_stroke":
                            # Check keywords
                            is_match = False
                            if p == "stroke_width":
                                if any(kw.arg == "width" for kw in stmt.value.keywords): is_match = True
                            elif p == "stroke_opacity":
                                if any(kw.arg == "opacity" for kw in stmt.value.keywords): is_match = True
                            
                            if is_match: is_existing_setter = True
                        else:
                            is_existing_setter = True

                    if is_existing_setter:
                        # Update existing setter instead of injecting!
                        lit = self._literal()
                        if p == "fill_opacity":
                            # set_fill(opacity=lit)
                            for kw in stmt.value.keywords:
                                if kw.arg == "opacity": kw.value = lit
                        elif p == "stroke_width":
                            for kw in stmt.value.keywords:
                                if kw.arg == "width": kw.value = lit
                        elif p == "stroke_opacity":
                            for kw in stmt.value.keywords:
                                if kw.arg == "opacity": kw.value = lit
                        else:
                            # set_color(lit)
                            if stmt.value.args: stmt.value.args[0] = lit
                            else: stmt.value.args.append(lit)
                        
                        output.append(stmt)
                        self.injected = True
                        logger.info(f"AST Surgery: Updated existing {target_setter} for {self.target}.{self.prop}")
                        continue

                    output.append(stmt)
                    
                    # Fallback: Inject after the creation line if no existing setter found
                    if not self.injected and getattr(stmt, "lineno", -1) == self.line:
                        injected_stmt = self._patch_stmt()
                        ast.copy_location(injected_stmt, stmt)
                        output.append(injected_stmt)
                        self.injected = True
                return output

            def generic_visit(self, node: ast.AST) -> ast.AST:
                super().generic_visit(node)
                for field, value in ast.iter_fields(node):
                    if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                        setattr(node, field, self._inject_into_stmt_list(value))
                return node

        injector = AssignmentInjector(
            target=target_var,
            prop=prop_name,
            value=new_value,
            line=ref.line_number,
        )
        self._tree = injector.visit(self._tree)
        ast.fix_missing_locations(self._tree)

        if injector.injected:
            logger.info(
                "Safe patch injected: %s.%s -> patch stmt after line %s",
                target_var,
                prop_name,
                ref.line_number,
            )
            return True

        logger.warning(
            "Safe patch failed: could not find insertion point for %s at line %s",
            target_var,
            ref.line_number,
        )
        return False

    def read_property(
        self, target_var: str, prop_name: str
    ) -> Optional[Any]:
        """Read a property value from the current AST.

        Used by State Reconciliation to sync GUI sliders
        after an external code edit.

        Args:
            target_var: Variable name (e.g., "circle")
            prop_name: Property name (e.g., "radius")

        Returns:
            The property value, or None if not found
        """
        # O(1) lookup via name index
        ref = self.get_binding_by_name(target_var)
        if ref:
            return ref.properties.get(prop_name)
        return None

    def update_property(
        self,
        target_var: str,
        prop_name: str,
        new_value: Any,
        source_key: Optional[str] = None,
    ) -> bool:
        """Surgically modify a property in the AST.

        Does NOT save to disk — call save_atomic() after.

        Args:
            target_var: Variable name (e.g., "circle")
            prop_name: Property name (e.g., "radius")
            new_value: New value to set

        Returns:
            True if the property was found and modified
        """
        if self._tree is None:
            logger.error("No file parsed yet. Call parse_file() first.")
            return False

        if self._file_path:
            try:
                self.parse_file(self._file_path)
            except Exception as e:
                logger.error(f"Failed to re-parse before update: {e}")
                return False

        strategy = self.plan_property_persistence(target_var, prop_name, source_key=source_key)
        if strategy.no_persist:
            logger.info("Skipping property update for %s.%s: %s", target_var, prop_name, strategy.reason)
            return False
        if strategy.safe_patch:
            return self._inject_post_creation_assignment(target_var, prop_name, new_value)

        updater = PropertyUpdater(target_var, prop_name, new_value)
        self._tree = updater.visit(self._tree)
        ast.fix_missing_locations(self._tree)

        if updater.was_modified:
            # Update our local bindings cache (O(1) via name index)
            ref = self.get_binding_by_name(target_var)
            if ref:
                ref.properties[prop_name] = new_value
            return True

        if updater.was_skipped:
            return False

        logger.warning(
            f"Property not found: {target_var}.{prop_name}"
        )
        return False

    def update_transform_method(
        self, target_var: str, method_name: str, value: float
    ) -> bool:
        """Modify or inject a standalone transform method like .scale() into the AST.

        Args:
            target_var: Variable name (e.g., 'circle')
            method_name: Transform method (e.g., 'scale')
            value: Float value to pass to the method
        """
        if self._tree is None:
            logger.error("No file parsed yet. Call parse_file() first.")
            return False

        if self._file_path:
            try:
                self.parse_file(self._file_path)
            except Exception as e:
                logger.error(f"Failed to re-parse before transform update: {e}")
                return False

        ref = self.get_binding_by_name(target_var)
        if not ref:
            return False
        if ref.transforms.get(method_name) == value:
            return True

        class TransformUpdater(ast.NodeTransformer):
            def __init__(self, target, method, val, creation_line):
                self.target = target
                self.method = method
                self.val = val
                self.creation_line = creation_line
                self.modified = False
                self.injected = False

            def visit_Expr(self, node: ast.Expr) -> ast.Expr:
                self.generic_visit(node)
                if not isinstance(node.value, ast.Call):
                    return node
                
                current = node.value
                while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
                    method_name = current.func.attr
                    
                    root_target = current.func.value
                    while isinstance(root_target, ast.Call) and isinstance(root_target.func, ast.Attribute):
                        root_target = root_target.func.value
                        
                    if isinstance(root_target, ast.Name) and root_target.id == self.target and method_name == self.method:
                        # Found existing method call! Update the argument.
                        if current.args:
                            current.args[0] = ast.Constant(value=self.val)
                        else:
                            current.args.append(ast.Constant(value=self.val))
                        self.modified = True
                        break
                        
                    current = current.func.value
                return node

            def visit_FunctionDef(self, n: ast.FunctionDef) -> ast.FunctionDef:
                self.generic_visit(n)
                if not self.modified and not self.injected:
                    new_body = []
                    for stmt in n.body:
                        new_body.append(stmt)
                        if getattr(stmt, 'lineno', -1) == self.creation_line:
                            # Inject right after object creation
                            transform_stmt = ast.Expr(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(id=self.target, ctx=ast.Load()),
                                        attr=self.method,
                                        ctx=ast.Load()
                                    ),
                                    args=[ast.Constant(value=self.val)],
                                    keywords=[]
                                )
                            )
                            ast.copy_location(transform_stmt, stmt)
                            new_body.append(transform_stmt)
                            self.injected = True
                    if self.injected:
                        n.body = new_body
                return n

        updater = TransformUpdater(target_var, method_name, value, ref.line_number)
        self._tree = updater.visit(self._tree)
        ast.fix_missing_locations(self._tree)

        if updater.modified:
            logger.info(f"AST Surgery: Updated {target_var}.{method_name}({value})")
        elif updater.injected:
            logger.info(f"AST Injection: Added {target_var}.{method_name}({value}) after line {ref.line_number}")
        
        # Update internal memory cache
        ref.transforms[method_name] = value

        return True

    def update_animation_method(
        self, target_var: str, old_method: str, new_method: str
    ) -> bool:
        """Modify an animation effect type in the AST.

        e.g. self.play(GrowFromCenter(circle)) -> self.play(SpinInFromNothing(circle))
        """
        if self._tree is None:
            return False

        if self._file_path:
            try:
                self.parse_file(self._file_path)
            except Exception as e:
                logger.error(f"Failed to re-parse before animation update: {e}")
                return False

        class AnimMethodUpdater(ast.NodeTransformer):
            def __init__(self, target, old_m, new_m):
                self.target = target
                self.old_m = old_m.lower()
                self.new_m = new_m
                self.modified = False

            def visit_Call(self, node: ast.Call) -> ast.Call:
                self.generic_visit(node)
                
                # We are looking for something like OldMethod(target)
                # Case 1: Simple Name (e.g., Create)
                # Case 2: Attribute (e.g., manim.Create)
                func_id = None
                if isinstance(node.func, ast.Name):
                    func_id = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_id = node.func.attr

                if func_id and func_id.lower() == self.old_m:
                    # Verify this animation is actually acting on our target object
                    is_our_target = False
                    if node.args:
                        arg0 = node.args[0]
                        # 1. Simple name match: Create(triangle)
                        if isinstance(arg0, ast.Name) and arg0.id == self.target:
                            is_our_target = True
                        # 2. Attribute match: Create(self.triangle)
                        elif (isinstance(arg0, ast.Attribute) and 
                              isinstance(arg0.value, ast.Name) and 
                              arg0.value.id == "self" and arg0.attr == self.target):
                            is_our_target = True
                        # 3. Chained match: Create(triangle.animate...)
                        else:
                            try:
                                arg_code = ast.unparse(arg0)
                                if self.target in arg_code:
                                    is_our_target = True
                            except: pass
                    
                    if is_our_target:
                        if isinstance(node.func, ast.Name):
                            node.func.id = self.new_m
                        elif isinstance(node.func, ast.Attribute):
                            node.func.attr = self.new_m
                        self.modified = True
                        logger.info(f"AST Surgery: Replaced {self.old_m} with {self.new_m} for {self.target}")
                
                return node

        updater = AnimMethodUpdater(target_var, old_method, new_method)
        self._tree = updater.visit(self._tree)
        if updater.modified:
            logger.info(f"AST Surgery: Replaced {old_method} with {new_method} for {target_var}")
            # Update cache
            for anim in self._animations:
                if anim.target_var == target_var and anim.method_name.lower() == old_method.lower():
                    anim.method_name = new_method.lower()
            
            return True
        return False

    def update_animation_kwarg(
        self, target_var: str, kwarg_name: str, value: float
    ) -> bool:
        """Modify an animation kwarg (e.g. run_time) in self.play()."""
        if self._tree is None:
            return False

        class AnimKwargUpdater(ast.NodeTransformer):
            def __init__(self, target):
                self.target = target
                self.modified = False

            def visit_Call(self, node: ast.Call) -> ast.Call:
                self.generic_visit(node)
                # Check if this is self.play
                if isinstance(node.func, ast.Attribute) and node.func.attr == 'play':
                    # Check if target is inside args
                    has_target = False
                    for arg in node.args:
                        # Case 1: Direct target play(FadeIn(triangle))
                        # Case 2: Animate play(triangle.animate.move_to(...))
                        arg_code = ast.unparse(arg)
                        if self.target in arg_code:
                            # Verify it's not just a substring, but our exact target
                            # (A bit naive but unparse + 'in' is very robust for this GUI)
                            has_target = True
                            break
                                
                    if has_target:
                        # Update or inject kwarg
                        lit = ast.Constant(value=value)
                        found = False
                        for kw in node.keywords:
                            if kw.arg == kwarg_name:
                                if isinstance(kw.value, ast.Constant):
                                    kw.value = lit
                                elif isinstance(kw.value, ast.IfExp) and getattr(kw.value.test, "value", False) is True:
                                    kw.value.body = lit
                                else:
                                    # Wrap complex expression
                                    kw.value = ast.IfExp(
                                        test=ast.Constant(value=True),
                                        body=lit,
                                        orelse=kw.value
                                    )
                                found = True
                                self.modified = True
                                break
                        if not found:
                            node.keywords.append(ast.keyword(arg=kwarg_name, value=lit))
                            self.modified = True

                return node

        updater = AnimKwargUpdater(target_var)
        self._tree = updater.visit(self._tree)
        
        if updater.modified:
            logger.info(f"AST Surgery: Updated self.play(..., {kwarg_name}={value}) for {target_var}")
            for anim in self._animations:
                if anim.target_var == target_var:
                    anim.kwargs[kwarg_name] = value
            
            return True
                    
        return False

    def update_animation_target(
        self,
        target_var: str,
        method_name: str,
        x: float,
        y: float,
        line_number: int,
    ) -> bool:
        """Surgically modify an animation target in the AST.

        e.g., self.play(circle.animate.move_to(RIGHT))
        → self.play(circle.animate.move_to([x, y, 0]))

        Args:
            target_var: The variable being animated (e.g., 'circle')
            method_name: The method being called (e.g., 'move_to', 'shift')
            x: New absolute X coordinate
            y: New absolute Y coordinate
            line_number: The line number of the animation call

        Returns:
            True if successful
        """
        if self._tree is None:
            logger.error("No file parsed yet. Call parse_file() first.")
            return False

        if self._file_path:
            try:
                self.parse_file(self._file_path)
            except Exception as e:
                logger.error(f"Failed to re-parse before animation update: {e}")
                return False

        # Attempt to resolve the freshest line number in case of external edits
        fresh_line = line_number
        for anim in self._animations:
            if anim.target_var == target_var and anim.method_name == method_name:
                # Naive matching: if multiple exist, this could match the first.
                # In a robust system, we'd compare UUIDs or full path, but this is a vast improvement.
                fresh_line = anim.line_number
                break

        class AnimationUpdater(ast.NodeTransformer):
            def __init__(self, target_var, method_name, x, y, line_number):
                self.target_var = target_var
                self.method_name = method_name
                self.x = x
                self.y = y
                self.line_number = line_number
                self.modified = False

            def visit_Call(self, node: ast.Call) -> ast.Call:
                self.generic_visit(node)
                
                # Check if this call is the method we want to update
                if getattr(node, 'lineno', -1) == self.line_number:
                    if isinstance(node.func, ast.Attribute) and node.func.attr == self.method_name:
                        if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == 'animate':
                            if isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == self.target_var:
                                # This is the exact .animate.method() call!
                                new_arg = ast.List(
                                    elts=[
                                        ast.Constant(value=self.x),
                                        ast.Constant(value=self.y),
                                        ast.Constant(value=0.0),
                                    ],
                                    ctx=ast.Load(),
                                )
                                
                                if node.args:
                                    arg0 = node.args[0]
                                    if isinstance(arg0, (ast.Constant, ast.List, ast.Tuple)):
                                        node.args[0] = new_arg
                                    elif isinstance(arg0, ast.IfExp) and getattr(arg0.test, "value", False) is True:
                                        arg0.body = new_arg
                                    else:
                                        # Complex expression — wrap it instead of losing it!
                                        node.args[0] = ast.IfExp(
                                            test=ast.Constant(value=True),
                                            body=new_arg,
                                            orelse=arg0
                                        )
                                else:
                                    node.args = [new_arg]
                                    
                                self.modified = True
                                logger.info(f"AST Animation Surgery: {self.target_var}.animate.{self.method_name} → [{self.x}, {self.y}, 0]")
                return node

        updater = AnimationUpdater(target_var, method_name, x, y, fresh_line)
        self._tree = updater.visit(self._tree)
        ast.fix_missing_locations(self._tree)

        if updater.modified:
            # Re-parse to update animations list
            finder = PropertyFinder()
            finder.visit(self._tree)
            self._animations = finder.animations
            
            return True

        logger.warning(f"Animation target not found for {target_var}.{method_name} at line {line_number}")
        return False

    def update_animation_position(
        self,
        animation_ref: ASTAnimationRef,
        absolute_x: float,
        absolute_y: float,
        base_center: Any,
    ) -> bool:
        """Persist a dragged animation position without changing semantics."""
        if self._tree is None:
            logger.error("No file parsed yet. Call parse_file() first.")
            return False
        if not getattr(animation_ref, "is_draggable", False):
            logger.info("Animation is not draggable: %s", animation_ref.animation_key)
            return False

        mode = animation_ref.position_mode
        if mode == "move_to":
            vector = [round(float(absolute_x), 2), round(float(absolute_y), 2), 0]
        else:
            bx = float(base_center[0]) if base_center is not None else 0.0
            by = float(base_center[1]) if base_center is not None else 0.0
            vector = [
                round(float(absolute_x) - bx, 2),
                round(float(absolute_y) - by, 2),
                0.0,
            ]

        new_node = ast.List(
            elts=[ast.Constant(value=value) for value in vector],
            ctx=ast.Load(),
        )

        class AnimationPositionUpdater(ast.NodeTransformer):
            def __init__(self, ref: ASTAnimationRef, replacement: ast.expr) -> None:
                self.ref = ref
                self.replacement = replacement
                self.modified = False

            def _animate_target_matches(self, node: ast.Call) -> bool:
                if not isinstance(node.func, ast.Attribute):
                    return False
                if node.func.attr != self.ref.method_name:
                    return False
                owner = node.func.value
                while isinstance(owner, ast.Call) and isinstance(owner.func, ast.Attribute):
                    owner = owner.func.value
                return (
                    isinstance(owner, ast.Attribute)
                    and owner.attr == "animate"
                    and isinstance(owner.value, ast.Name)
                    and owner.value.id == self.ref.target_var
                )

            def _effect_target_matches(self, node: ast.Call) -> bool:
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name.lower() != self.ref.method_name.lower():
                    return False
                return bool(
                    node.args
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == self.ref.target_var
                )

            def visit_Call(self, node: ast.Call) -> ast.Call:
                self.generic_visit(node)
                if self.ref.position_mode in {"move_to", "shift"} and self._animate_target_matches(node):
                    if node.args:
                        node.args[0] = self.replacement
                    else:
                        node.args.append(self.replacement)
                    self.modified = True
                elif self.ref.position_mode == "effect_shift" and self._effect_target_matches(node):
                    for kw in node.keywords:
                        if kw.arg == "shift":
                            kw.value = self.replacement
                            self.modified = True
                            break
                    if not self.modified:
                        node.keywords.append(ast.keyword(arg="shift", value=self.replacement))
                        self.modified = True
                return node

        updater = AnimationPositionUpdater(animation_ref, new_node)
        self._tree = updater.visit(self._tree)
        ast.fix_missing_locations(self._tree)
        if updater.modified:
            self._rebuild_metadata_from_tree()
            return True
        logger.warning("Animation position target not found: %s", animation_ref.animation_key)
        return False

    def repair_source_compatibility(self) -> bool:
        """Repair known Manim constructor incompatibilities safely.

        Example: some scenes pass ``dash_length`` to ``Line``. Manim expects
        that argument on ``DashedLine``, so we upgrade only that exact call.
        """
        if self._tree is None:
            return False

        class CompatibilityRepair(ast.NodeTransformer):
            def __init__(self) -> None:
                self.modified = False
                self.needs_dashed_line_import = False

            def visit_Call(self, node: ast.Call) -> ast.Call:
                self.generic_visit(node)
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name == "Line" and any(kw.arg == "dash_length" for kw in node.keywords):
                    if isinstance(node.func, ast.Name):
                        node.func.id = "DashedLine"
                    else:
                        node.func.attr = "DashedLine"
                    self.modified = True
                    self.needs_dashed_line_import = True
                return node

            def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
                self.generic_visit(node)
                if node.module == "manim" and self.needs_dashed_line_import:
                    if not any(alias.name == "DashedLine" for alias in node.names):
                        node.names.append(ast.alias(name="DashedLine"))
                        self.modified = True
                return node

        repair = CompatibilityRepair()
        self._tree = repair.visit(self._tree)
        if repair.needs_dashed_line_import:
            # Run a second pass so import nodes seen before call nodes get updated.
            self._tree = repair.visit(self._tree)
        ast.fix_missing_locations(self._tree)
        if repair.modified:
            self._rebuild_metadata_from_tree()
        return repair.modified

    def _generate_format_preserving_source(self) -> str:
        """Generate source that preserves original formatting.

        Instead of ast.unparse(whole_tree) which destroys comments,
        blank lines, and indentation, this method:
        1. Re-parses the original source to get a baseline AST
        2. Walks all statement bodies comparing individual statements
        3. Only replaces source lines where statements actually changed
        4. Inserts newly injected statements with correct indentation
        5. Keeps everything else (comments, blanks, formatting) verbatim

        Returns:
            The patched source string preserving original formatting.
        """
        if self._source is None or self._tree is None:
            return ast.unparse(self._tree) + "\n"

        source_lines = self._source.splitlines(keepends=True)
        # Ensure last line has a newline
        if source_lines and not source_lines[-1].endswith("\n"):
            source_lines[-1] += "\n"

        try:
            original_tree = ast.parse(self._source)
        except SyntaxError:
            # Original source is broken — fall back to full unparse
            return ast.unparse(self._tree) + "\n"

        # Collect all statements from every body (module, class, function)
        # in the original tree, keyed by (lineno, end_lineno)
        orig_fingerprints = {}
        self._collect_stmt_fingerprints(original_tree, orig_fingerprints)

        # Walk the modified tree and find diffs / injections
        edits = []       # (start_line, end_line, replacement_text)
        injections = []  # (after_line, text)
        self._diff_tree_bodies(self._tree, orig_fingerprints, source_lines, edits, injections)

        # Apply edits from bottom-to-top so line numbers stay valid
        result = list(source_lines)
        for start, end, text in sorted(edits, key=lambda x: x[0], reverse=True):
            result[start - 1 : end] = text.splitlines(keepends=True)

        # Apply injections from bottom-to-top
        for after_line, text in sorted(injections, key=lambda x: x[0], reverse=True):
            insert_idx = min(after_line, len(result))
            result.insert(insert_idx, text if text.endswith("\n") else text + "\n")

        return "".join(result)

    def _collect_stmt_fingerprints(
        self, tree: ast.AST, out: dict[tuple[int, int], str]
    ) -> None:
        """Build a map of (lineno, end_lineno) → ast.unparse(stmt) for ALL
        statements in every body node of the original tree."""
        for node in ast.walk(tree):
            body_lists = []
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body_lists.append(getattr(node, "body", []))
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try)):
                body_lists.append(getattr(node, "body", []))
                body_lists.append(getattr(node, "orelse", []))
            if isinstance(node, ast.Try):
                for handler in getattr(node, "handlers", []):
                    body_lists.append(getattr(handler, "body", []))
                body_lists.append(getattr(node, "finalbody", []))
            for body in body_lists:
                for stmt in body:
                    lineno = getattr(stmt, "lineno", None)
                    end_lineno = getattr(stmt, "end_lineno", None)
                    if lineno is not None and end_lineno is not None:
                        try:
                            out[(lineno, end_lineno)] = ast.unparse(stmt)
                        except Exception:
                            pass

    def _diff_tree_bodies(
        self,
        tree: ast.AST,
        orig_fingerprints: dict[tuple[int, int], str],
        source_lines: list[str],
        edits: list,
        injections: list,
    ) -> None:
        """Walk modified tree bodies, compare to original fingerprints,
        and populate edits/injections lists."""
        seen_keys = set()
        for node in ast.walk(tree):
            body_lists = []
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body_lists.append(getattr(node, "body", []))
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try)):
                body_lists.append(getattr(node, "body", []))
                body_lists.append(getattr(node, "orelse", []))
            if isinstance(node, ast.Try):
                for handler in getattr(node, "handlers", []):
                    body_lists.append(getattr(handler, "body", []))
                body_lists.append(getattr(node, "finalbody", []))

            for body in body_lists:
                for stmt in body:
                    lineno = getattr(stmt, "lineno", None)
                    end_lineno = getattr(stmt, "end_lineno", None)
                    if lineno is None or end_lineno is None:
                        continue

                    key = (lineno, end_lineno)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                    try:
                        new_unparse = ast.unparse(stmt)
                    except Exception:
                        continue

                    if key in orig_fingerprints:
                        orig_unparse = orig_fingerprints[key]
                        if orig_unparse != new_unparse:
                            # MODIFIED statement — replace those source lines
                            indent = self._detect_indent(source_lines, lineno)
                            replacement = self._indent_code(new_unparse, indent)
                            edits.append((lineno, end_lineno, replacement))
                    else:
                        # INJECTED statement — no matching lines in original
                        indent = self._detect_indent(source_lines, lineno)
                        text = self._indent_code(new_unparse, indent)
                        injections.append((lineno, text))

    @staticmethod
    def _detect_indent(source_lines: list[str], lineno: int) -> str:
        """Detect the indentation string used at a given line number."""
        if 1 <= lineno <= len(source_lines):
            line = source_lines[lineno - 1]
            stripped = line.lstrip()
            if stripped:
                return line[: len(line) - len(stripped)]
        # Fallback: 8 spaces (standard Manim construct body indent)
        return "        "

    @staticmethod
    def _indent_code(code: str, indent: str) -> str:
        """Indent a code string. First line gets indent, continuation
        lines get indent + 4 spaces for readability."""
        lines = code.split("\n")
        result_lines = []
        for i, line in enumerate(lines):
            if i == 0:
                result_lines.append(indent + line)
            elif line.strip():
                result_lines.append(indent + "    " + line)
            else:
                result_lines.append("")
        return "\n".join(result_lines) + "\n"

    def save_atomic(self, path: str | Path | None = None) -> bool:
        """Atomically save the modified AST back to disk.

        Uses format-preserving source patching to keep comments,
        blank lines, and indentation intact. Only the specific lines
        containing modified AST statements are regenerated.

        Uses tempfile + os.rename for corruption-proof writes.

        Args:
            path: Path to save to (defaults to the parsed file)

        Returns:
            True if save succeeded
        """
        if self._tree is None:
            logger.error("No AST to save. Call parse_file() first.")
            return False

        path = Path(path) if path else self._file_path
        if path is None:
            logger.error("No file path specified.")
            return False

        try:
            # Generate format-preserving patched source
            new_source = self._generate_format_preserving_source()

            # Validate the patched source compiles (safety net)
            try:
                ast.parse(new_source)
            except SyntaxError as e:
                logger.warning(f"Patched source has syntax error, falling back to ast.unparse: {e}")
                new_source = ast.unparse(self._tree) + "\n"

            if self._source is not None and self._source.rstrip() == new_source.rstrip():
                self.last_error = None
                return True

            # Atomic write: write to temp file, then rename
            dir_path = path.parent
            fd, tmp_path = tempfile.mkstemp(
                dir=str(dir_path),
                suffix=".py.tmp",
                prefix=".bisync_",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(new_source)
                    if not new_source.endswith("\n"):
                        f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename (POSIX guarantee)
                os.rename(tmp_path, str(path))
                self._source = new_source
                self._tree = ast.parse(new_source, filename=str(path))
                self._rebuild_metadata_from_tree()
                self.last_error = None
                logger.info(f"Atomic save (format-preserving): {path.name}")
                return True

            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Save failed: {e}")
            return False

    # ────────────────────────────────────────────────────────────
    # Socket 4: Live Binds (mobject_id → AST node)
    # ────────────────────────────────────────────────────────────

    def register_live_bind(
        self, mobject_id: int, variable_name: str
    ) -> None:
        """Register a link between a rendered Mobject and its AST node.

        Socket 4: Phase 4's Mouse Ray-Caster will use this to find
        the exact code line when a user clicks on a shape.

        Args:
            mobject_id: Python id() of the Mobject
            variable_name: The variable name in source code
        """
        # O(1) lookup via name index
        ref = self.get_binding_by_name(variable_name)
        
        if ref is not None:
            self._live_binds[mobject_id] = ref
            pass




    def get_live_bind(self, mobject_id: int) -> Optional[ASTNodeRef]:
        """Get the AST reference for a rendered Mobject.

        Phase 4 calls this when a user clicks on a shape to find
        which code line to modify.
        """
        return self._live_binds.get(mobject_id)

    def get_all_properties(self) -> dict[str, dict[str, Any]]:
        """Return all variable properties for GUI slider sync.

        Returns:
            {variable_name: {prop_name: value, ...}, ...}
        """
        return {
            ref.variable_name: ref.properties.copy()
            for ref in self._bindings.values()
        }
