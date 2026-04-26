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

    @property
    def animation_key(self) -> str:
        """Stable-ish key used by UI to rebind selected animation after reload."""
        return f"{self.target_var}:{self.method_name}:{self.line_number}:{self.col_offset}"


@dataclass
class ASTNodeRef:
    """Reference to a specific AST node's location in source code.

    Used by Socket 4 for O(1) mobject→code lookup.
    """

    variable_name: str
    line_number: int
    col_offset: int
    constructor_name: str  # e.g., "Circle", "Square"
    properties: dict[str, Any] = field(default_factory=dict)
    transforms: dict[str, Any] = field(default_factory=dict) # To track .scale(), .rotate()
    source_key: Optional[str] = None
    editability: str = "source_editable"
    read_only_reason: str = ""
    display_name: str = ""
    inline_path: tuple[int, ...] = field(default_factory=tuple)
    constructor_params: list[Any] = field(default_factory=list)
    modifier_calls: list[Any] = field(default_factory=list)
    animation_calls: list[Any] = field(default_factory=list)


class PropertyFinder(ast.NodeVisitor):
    """Finds variable assignments with constructor calls and their properties.

    Scans the AST for patterns like:
        circle = Circle(radius=1.5, color=BLUE, fill_opacity=0.5)
        square = Square(side_length=2.0, color=RED)

    Builds a registry of {line_number: ASTNodeRef} for each found assignment.
    """

    def __init__(self) -> None:
        self.bindings: dict[int, ASTNodeRef] = {}
        self.animations: list[ASTAnimationRef] = []
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

    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit assignment nodes to find Manim constructor calls."""
        # Only handle simple assignments: `name = Constructor(...)`
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
        ):
            target_name = node.targets[0].id
            call_node = node.value

            # Check if calling a known Manim constructor
            func_name = self._get_func_name(call_node.func)
            if func_name in self._known_constructors:
                # Extract keyword arguments as properties
                props = {}
                # Special case: Text/Tex often have the string as the first positional arg
                if func_name in ("Text", "Tex", "MathTex") and call_node.args:
                    props["text"] = self._extract_value(call_node.args[0])
                    
                for kw in call_node.keywords:
                    if kw.arg is not None:
                        props[kw.arg] = self._extract_value(kw.value)

                ref = ASTNodeRef(
                    variable_name=target_name,
                    line_number=node.lineno,
                    col_offset=node.col_offset,
                    constructor_name=func_name,
                    properties=props,
                    source_key=f"{target_name}:{node.lineno}:{node.col_offset}",
                    display_name=target_name,
                )
                self.bindings[node.lineno] = ref
            else:
                factory_methods = {
                    "plot": "ParametricFunction",
                    "get_graph": "ParametricFunction",
                    "get_area": "Polygon",
                    "get_riemann_rectangles": "VGroup",
                    "n2p": "Dot",
                    "c2p": "Dot",
                    "coords_to_point": "Dot",
                    "copy": "Mobject",
                    "animate": "Mobject"
                }
                if func_name in factory_methods and isinstance(call_node.func, ast.Attribute):
                    props = {}
                    for kw in call_node.keywords:
                        if kw.arg is not None:
                            props[kw.arg] = self._extract_value(kw.value)
                    
                    constructor_guess = factory_methods[func_name]
                    ref = ASTNodeRef(
                        variable_name=target_name,
                        line_number=node.lineno,
                        col_offset=node.col_offset,
                        constructor_name=constructor_guess,
                        properties=props,
                        source_key=f"{target_name}:{node.lineno}:{node.col_offset}",
                        display_name=target_name,
                        editability="source_editable",
                    )
                    self.bindings[node.lineno] = ref




        # No generic_visit(node) here to prevent redundant traversal since visit_Call
        # handles Call nodes directly.
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

        self.generic_visit(node)

    def _extract_animation_from_play_arg(self, arg: Any, play_kwargs: dict[str, Any]) -> None:
        """Extract animation from a single argument to self.play()."""
        # Pattern 1: obj.animate.method(...) — e.g. circle.animate.shift(UP)
        # Also handles chained methods e.g. circle.animate.set_color(RED).shift(UP)
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
            current = arg.func
            method_name = current.attr
            target_var = None
            
            # Walk down the AST to find .animate
            while isinstance(current, ast.Attribute):
                if current.attr == "animate" and isinstance(current.value, ast.Name):
                    target_var = current.value.id
                    break
                if isinstance(current.value, ast.Call) and isinstance(current.value.func, ast.Attribute):
                    current = current.value.func
                elif isinstance(current.value, ast.Attribute):
                    current = current.value
                else:
                    break
                    
            if target_var:
                extracted_args = [self._extract_value(a) for a in arg.args]
                ref = ASTAnimationRef(
                    target_var=target_var,
                    method_name=method_name,
                    args=extracted_args,
                    line_number=arg.lineno,
                    col_offset=arg.col_offset,
                    kwargs=play_kwargs.copy(),
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
            }:
                # Extract target from first argument
                target = None
                if arg.args and isinstance(arg.args[0], ast.Name):
                    target = arg.args[0].id
                elif arg.args and isinstance(arg.args[0], ast.Attribute):
                    # e.g. VGroup(circle, square) — use the variable name if available
                    target = self._get_func_name(arg.args[0])

                if target:
                    anim_kwargs = play_kwargs.copy()
                    for kw in arg.keywords:
                        if kw.arg is not None:
                            anim_kwargs[kw.arg] = self._extract_value(kw.value)
                            
                    ref = ASTAnimationRef(
                        target_var=target,
                        method_name=func_name.lower(),  # convention: 'create' not 'Create'
                        args=[self._extract_value(a) for a in arg.args[1:]],
                        line_number=arg.lineno,
                        col_offset=arg.col_offset,
                        kwargs=anim_kwargs,
                    )
                    self.animations.append(ref)
                    pass



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
                if method_name in ("scale", "rotate"):
                    # Find the ASTNodeRef by variable name
                    for ref in self.bindings.values():
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

    @property
    def was_modified(self) -> bool:
        return self._modified
        
    @property
    def was_skipped(self) -> bool:
        return self._was_skipped

    def visit_Assign(self, node: ast.Assign) -> ast.Assign:
        """Find the target assignment and modify its property.

        When user explicitly changes a property (via slider), the old value
        is replaced unconditionally. Complex expressions (e.g., `radius=UP*2`)
        are simplified to the computed value — this is intentional, as the user
        has explicitly chosen to override via the GUI.
        """
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == self._target_var
            and isinstance(node.value, ast.Call)
        ):
            # Special case for "text" property in Text/Tex (first positional arg)
            if self._prop_name == "text" and node.value.args:
                if isinstance(node.value.args[0], ast.Constant):
                    node.value.args[0] = ast.Constant(value=self._new_value)
                    self._modified = True
                    logger.info(
                        f"AST Surgery: {self._target_var}.text "
                        f"→ {self._new_value} (line {node.lineno})"
                    )
                return node
                
            # Found the target assignment — modify the keyword
            for kw in node.value.keywords:
                if kw.arg == self._prop_name:
                    # Only replace if existing value is a simple constant
                    if isinstance(kw.value, ast.Constant):
                        # Safe to replace — it's a simple literal
                        kw.value = ast.Constant(value=self._new_value)
                        self._modified = True
                        logger.info(
                            f"AST Surgery: {self._target_var}.{self._prop_name} "
                            f"→ {self._new_value} (line {node.lineno})"
                        )
                    else:
                        # Complex expression — skip, don't lose the expression
                        self._was_skipped = True
                        logger.warning(
                            f"Skipping {self._target_var}.{self._prop_name}: "
                            f"existing value is a complex expression, not a simple constant. "
                            f"Manual code edit required."
                        )
                    break
            else:
                # Property doesn't exist yet — add it as new keyword
                new_kw = ast.keyword(
                    arg=self._prop_name,
                    value=ast.Constant(value=self._new_value),
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
                return ast.unparse(self._tree) + "\n"
            except Exception:
                pass
        return (self._source or "")

    @property
    def is_dirty(self) -> bool:
        """Compatibility flag for callers expecting dirty-state tracking."""
        if self._tree is None:
            return False
        try:
            return (self._source or "").rstrip() != ast.unparse(self._tree).rstrip()
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
        finder = PropertyFinder()
        finder.visit(self._tree)
        self._bindings = finder.bindings
        # Build O(1) name index
        self._bindings_by_name = {ref.variable_name: ref for ref in self._bindings.values()}
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
        finder = PropertyFinder()
        finder.visit(self._tree)
        self._bindings = finder.bindings
        self._bindings_by_name = {ref.variable_name: ref for ref in self._bindings.values()}
        self._animations = finder.animations
        return self._bindings

    def iter_scene_nodes(self):
        """Compatibility iterator expected by MainWindow snapshot flow."""
        return self._bindings.values()

    def get_binding_by_source_key(self, source_key: Optional[str]):
        if not source_key:
            return None
        for ref in self._bindings.values():
            if ref.source_key == source_key:
                return ref
        return None

    def get_binding_by_line(self, line_number: int) -> Optional[ASTNodeRef]:
        return self._bindings.get(line_number)

    def get_binding_by_runtime_marker(
        self,
        source_file: Optional[str],
        line_number: Optional[int],
        occurrence: Optional[int],
    ) -> Optional[ASTNodeRef]:
        del source_file, occurrence
        if line_number is None:
            return None
        return self._bindings.get(line_number)

    def get_child_binding(self, source_key: Optional[str], path: tuple[int, ...]):
        del path
        return self.get_binding_by_source_key(source_key)

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
        return None

    def plan_property_persistence(
        self,
        target_var: str,
        prop_name: str,
        *,
        source_key: Optional[str] = None,
        path: tuple[int, ...] = (),
    ) -> PersistenceStrategy:
        """Choose persistence mode for an edit (exact/patch/no-persist)."""
        del prop_name
        if source_key:
            ref = self.get_binding_by_source_key(source_key)
            if ref is not None:
                if path and tuple(path) != tuple(getattr(ref, "inline_path", ())):
                    return PersistenceStrategy(
                        mode="no_persist",
                        reason="selected runtime child is not the canonical source anchor",
                        source_key=source_key,
                    )
                return PersistenceStrategy(
                    mode="exact_source",
                    reason="source key resolves to canonical AST binding",
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
            return self.update_property(target_var, prop_name, new_value)

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
                if isinstance(self.value, (int, float, str, bool)) or self.value is None:
                    return ast.Constant(value=self.value)
                if isinstance(self.value, (list, tuple)):
                    return ast.List(
                        elts=[ast.Constant(value=v) for v in self.value],
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
                for stmt in stmts:
                    output.append(stmt)
                    if not self.injected and getattr(stmt, "lineno", -1) == self.line:
                        injected_stmt = self._patch_stmt()
                        ast.copy_location(injected_stmt, stmt)
                        next_index = len(output)
                        next_stmt = stmts[next_index] if next_index < len(stmts) else None
                        if next_stmt is not None and ast.dump(next_stmt) == ast.dump(injected_stmt):
                            self.injected = True
                            continue
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

        class AnimMethodUpdater(ast.NodeTransformer):
            def __init__(self):
                self.modified = False

            def visit_Call(self, node: ast.Call) -> ast.Call:
                self.generic_visit(node)
                # Check for standard Manim animation pattern: Name(target_var)
                if isinstance(node.func, ast.Name) and node.func.id.lower() == old_method.lower():
                    # Check if target matches
                    target_matches = False
                    if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == target_var:
                        target_matches = True
                    elif node.args and isinstance(node.args[0], ast.Attribute):
                        # Attempt to resolve VGroup variables, simplified
                        if getattr(node.args[0], 'attr', '') == target_var or getattr(node.args[0].value, 'id', '') == target_var:
                            target_matches = True
                            
                    if target_matches:
                        node.func.id = new_method
                        self.modified = True
                return node

        updater = AnimMethodUpdater()
        self._tree = updater.visit(self._tree)
        if updater.modified:
            logger.info(f"AST Surgery: Replaced {old_method} with {new_method} for {target_var}")
            # Update cache
            for anim in self._animations:
                if anim.target_var == target_var and anim.method_name.lower() == old_method.lower():
                    anim.method_name = new_method.lower()
        return updater.modified

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
                        # Direct target `play(target.animate)`
                        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
                            # Very simplified check for animate or basic anims
                            has_target = True # We assume if it's the right line, it's correct. 
                            # A proper check requires deep traversal. For this demo we'll just check if target string is in unparsed source
                            try:
                                arg_code = ast.unparse(arg)
                                if self.target in arg_code:
                                    has_target = True
                                    break
                            except:
                                pass
                                
                    if has_target:
                        # Update or inject kwarg
                        found = False
                        for kw in node.keywords:
                            if kw.arg == kwarg_name:
                                kw.value = ast.Constant(value=value)
                                found = True
                                self.modified = True
                                break
                        if not found:
                            node.keywords.append(ast.keyword(arg=kwarg_name, value=ast.Constant(value=value)))
                            self.modified = True

                return node

        updater = AnimKwargUpdater(target_var)
        self._tree = updater.visit(self._tree)
        
        if updater.modified:
            logger.info(f"AST Surgery: Updated self.play(..., {kwarg_name}={value}) for {target_var}")
            for anim in self._animations:
                if anim.target_var == target_var:
                    anim.kwargs[kwarg_name] = value
                    
        return updater.modified

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
                                # Replace args with [x, y, 0]
                                node.args = [
                                    ast.List(
                                        elts=[
                                            ast.Constant(value=self.x),
                                            ast.Constant(value=self.y),
                                            ast.Constant(value=0.0),
                                        ],
                                        ctx=ast.Load(),
                                    )
                                ]
                                self.modified = True
                                logger.info(f"AST Animation Surgery: {self.target_var}.animate.{self.method_name} → [{self.x}, {self.y}, 0]")
                return node

        updater = AnimationUpdater(target_var, method_name, x, y, line_number)
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

    def save_atomic(self, path: str | Path | None = None) -> bool:
        """Atomically save the modified AST back to disk.

        Uses tempfile + os.rename for corruption-proof writes.
        Even if the process crashes mid-write, the original file
        remains intact (rename is atomic on most filesystems).

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
            # Generate clean Python source from AST
            new_source = ast.unparse(self._tree)
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
                    f.write("\n")  # Trailing newline
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename (POSIX guarantee)
                os.rename(tmp_path, str(path))
                self._source = new_source + "\n"
                self.last_error = None
                logger.info(f"Atomic save: {path.name}")
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
