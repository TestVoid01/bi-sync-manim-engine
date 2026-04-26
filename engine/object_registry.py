"""
Bi-Sync Object Registry
=======================

Tracks the live scene graph with stable metadata so selection,
inspection, and AST writes do not depend on ad-hoc string matching.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from engine.ast_mutator import ASTMutator, SceneNodeRef

logger = logging.getLogger("bisync.object_registry")


@dataclass
class LiveObjectRef:
    """Registry entry for a live rendered mobject."""

    mobject_id: int
    top_level_id: int
    variable_name: Optional[str]
    line_number: Optional[int]
    constructor_name: str
    source_key: Optional[str] = None
    editability: str = "live_read_only"
    read_only_reason: str = ""
    source_display_name: str = ""
    path: tuple[int, ...] = ()
    parent_id: Optional[int] = None
    is_top_level: bool = False

    @property
    def display_name(self) -> str:
        base = self.source_display_name or self.variable_name or self.constructor_name
        return base + "".join(f"[{index}]" for index in self.path)


@dataclass
class SelectionRef:
    """Canonical selection payload emitted to the UI."""

    mobject_id: int
    top_level_id: int
    variable_name: str
    line_number: Optional[int]
    constructor_name: str
    source_key: Optional[str] = None
    editability: str = "live_read_only"
    read_only_reason: str = ""
    path: tuple[int, ...] = ()
    display_name: str = ""

    @property
    def key(self) -> str:
        return f"{self.source_key or self.variable_name}:{self.path}"


class ObjectRegistry:
    """Maps live mobject ids to canonical AST-backed identities."""

    def __init__(self) -> None:
        self._refs_by_id: dict[int, LiveObjectRef] = {}
        self._top_level_ids_by_var: dict[str, int] = {}
        self._source_key_to_id: dict[str, int] = {}

    def clear(self) -> None:
        self._refs_by_id.clear()
        self._top_level_ids_by_var.clear()
        self._source_key_to_id.clear()

    def register_scene(self, scene: Any, ast_mutator: ASTMutator) -> None:
        """Rebuild the registry from the current live Manim scene."""
        self.clear()

        clear_live_binds = getattr(ast_mutator, "clear_live_binds", None)
        if callable(clear_live_binds):
            clear_live_binds()
        elif hasattr(ast_mutator, "_live_binds"):
            ast_mutator._live_binds.clear()

        for mob in getattr(scene, "mobjects", []):
            source_file = getattr(mob, "_bisync_source_file", None)
            line_number = getattr(mob, "_bisync_line_number", None)
            occurrence = getattr(mob, "_bisync_occurrence", None)
            ast_ref = self._get_ast_ref(ast_mutator, source_file, line_number, occurrence)
            top_ref = self._register_mobject(
                mob=mob,
                ast_ref=ast_ref,
                top_level_id=id(mob),
                parent_id=None,
                path=(),
                is_top_level=True,
            )
            if ast_ref is not None and ast_ref.variable_name:
                ast_mutator.register_live_bind(id(mob), ast_ref.variable_name)
            self._register_submobjects(
                mob=mob,
                ast_ref=ast_ref,
                top_level_id=top_ref.top_level_id,
                parent_id=top_ref.mobject_id,
                path=(),
                ast_mutator=ast_mutator,
            )

        logger.info("ObjectRegistry registered %d live mobjects", len(self._refs_by_id))

    def get(self, mobject_id: int) -> Optional[LiveObjectRef]:
        return self._refs_by_id.get(mobject_id)

    def get_by_variable_name(self, variable_name: str) -> Optional[LiveObjectRef]:
        top_level_id = self._top_level_ids_by_var.get(variable_name)
        if top_level_id is None:
            return None
        return self._refs_by_id.get(top_level_id)

    def get_by_source_key(self, source_key: str) -> Optional[LiveObjectRef]:
        ref_id = self._source_key_to_id.get(source_key)
        if ref_id is None:
            return None
        return self._refs_by_id.get(ref_id)

    def create_selection(
        self,
        top_level_mobject_id: int,
        selected_mobject_id: int,
        path: tuple[int, ...] = (),
    ) -> Optional[SelectionRef]:
        """Build the UI-facing selection from registry entries."""
        top_ref = self.get(top_level_mobject_id)
        if top_ref is None:
            return None

        selected_ref = self.get(selected_mobject_id) or top_ref
        source_ref = selected_ref
        if source_ref.source_key is None:
            source_ref = top_ref

        if source_ref.source_key is None:
            runtime_name = selected_ref.constructor_name
            display_name = runtime_name + "".join(f"[{index}]" for index in path)
            return SelectionRef(
                mobject_id=selected_ref.mobject_id,
                top_level_id=top_ref.top_level_id,
                variable_name=f"__runtime_{selected_ref.mobject_id}",
                line_number=selected_ref.line_number,
                constructor_name=selected_ref.constructor_name,
                source_key=None,
                editability="live_read_only",
                read_only_reason="runtime object has no exact source anchor",
                path=tuple(path),
                display_name=display_name,
            )

        display_name = source_ref.display_name
        return SelectionRef(
            mobject_id=selected_ref.mobject_id,
            top_level_id=top_ref.top_level_id,
            variable_name=source_ref.variable_name or source_ref.display_name,
            line_number=source_ref.line_number,
            constructor_name=source_ref.constructor_name,
            source_key=source_ref.source_key,
            editability=source_ref.editability,
            read_only_reason=source_ref.read_only_reason,
            path=tuple(path),
            display_name=display_name,
        )

    def find_mobject(self, scene: Any, mobject_id: int) -> Optional[Any]:
        """Locate a live mobject by id inside the current scene graph."""

        def walk(mob: Any) -> Optional[Any]:
            if id(mob) == mobject_id:
                return mob
            for sub in getattr(mob, "submobjects", []):
                found = walk(sub)
                if found is not None:
                    return found
            return None

        for mob in getattr(scene, "mobjects", []):
            found = walk(mob)
            if found is not None:
                return found
        return None

    def find_mobject_by_path(
        self,
        scene: Any,
        top_level_id: int,
        path: tuple[int, ...],
    ) -> Optional[Any]:
        """Resolve a selected child path under a registered top-level mobject."""
        top_level = self.find_mobject(scene, top_level_id)
        if top_level is None:
            return None

        current = top_level
        for index in path:
            submobjects = getattr(current, "submobjects", [])
            if index < 0 or index >= len(submobjects):
                return None
            current = submobjects[index]
        return current

    def find_mobject_by_source_key(self, scene: Any, source_key: str) -> Optional[Any]:
        live_ref = self.get_by_source_key(source_key)
        if live_ref is None:
            return None
        return self.find_mobject(scene, live_ref.mobject_id)

    def _register_submobjects(
        self,
        mob: Any,
        ast_ref: Optional[SceneNodeRef],
        top_level_id: int,
        parent_id: int,
        path: tuple[int, ...],
        ast_mutator: ASTMutator,
    ) -> None:
        for index, sub in enumerate(getattr(mob, "submobjects", [])):
            sub_path = path + (index,)
            child_ast_ref = (
                ast_mutator.get_child_binding(ast_ref.source_key, sub_path)
                if ast_ref is not None and getattr(ast_mutator, "get_child_binding", None)
                else None
            )
            self._register_mobject(
                mob=sub,
                ast_ref=child_ast_ref or ast_ref,
                top_level_id=top_level_id,
                parent_id=parent_id,
                path=sub_path,
                is_top_level=False,
            )
            effective_ref = child_ast_ref or ast_ref
            if effective_ref is not None and effective_ref.variable_name:
                ast_mutator.register_live_bind(id(sub), effective_ref.variable_name)
            self._register_submobjects(
                mob=sub,
                ast_ref=effective_ref,
                top_level_id=top_level_id,
                parent_id=id(sub),
                path=sub_path,
                ast_mutator=ast_mutator,
            )

    def _register_mobject(
        self,
        mob: Any,
        ast_ref: Optional[SceneNodeRef],
        top_level_id: int,
        parent_id: Optional[int],
        path: tuple[int, ...],
        is_top_level: bool,
    ) -> LiveObjectRef:
        line_number = (
            ast_ref.line_number
            if ast_ref is not None
            else getattr(mob, "_bisync_line_number", None)
        )
        ref = LiveObjectRef(
            mobject_id=id(mob),
            top_level_id=top_level_id,
            variable_name=ast_ref.variable_name if ast_ref is not None else None,
            line_number=line_number,
            constructor_name=type(mob).__name__,
            source_key=ast_ref.source_key if ast_ref is not None else None,
            editability=ast_ref.editability if ast_ref is not None else "live_read_only",
            read_only_reason=ast_ref.read_only_reason if ast_ref is not None else "runtime object has no exact source anchor",
            source_display_name=ast_ref.display_name if ast_ref is not None else type(mob).__name__,
            path=path,
            parent_id=parent_id,
            is_top_level=is_top_level,
        )
        self._refs_by_id[ref.mobject_id] = ref
        if ref.is_top_level and ref.variable_name:
            self._top_level_ids_by_var[ref.variable_name] = ref.mobject_id
        if ref.source_key and (ref.path == getattr(ast_ref, "inline_path", ()) if ast_ref is not None else ref.is_top_level):
            self._source_key_to_id.setdefault(ref.source_key, ref.mobject_id)
        return ref

    @staticmethod
    def _get_ast_ref(
        ast_mutator: ASTMutator,
        source_file: Optional[str],
        line_number: Optional[int],
        occurrence: Optional[int],
    ) -> Optional[SceneNodeRef]:
        if line_number is None:
            return None
        get_binding_by_runtime_marker = getattr(ast_mutator, "get_binding_by_runtime_marker", None)
        if callable(get_binding_by_runtime_marker):
            ref = get_binding_by_runtime_marker(source_file, line_number, occurrence)
            if ref is not None:
                return ref
            owns_source_file = getattr(ast_mutator, "owns_source_file", None)
            if source_file and callable(owns_source_file):
                return None
        get_binding_by_line = getattr(ast_mutator, "get_binding_by_line", None)
        if callable(get_binding_by_line):
            return get_binding_by_line(line_number)
        return ast_mutator.bindings.get(line_number)
