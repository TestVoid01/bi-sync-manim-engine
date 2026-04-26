"""
Bi-Sync Property Inspector
==========================

Builds grouped, code-first PropertySpec objects from:
1. explicit AST constructor params
2. explicit AST modifier/animation params
3. live object inspection as fallback
"""

from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import logging
import math
from numbers import Integral, Real
from typing import TYPE_CHECKING, Any, Callable, Optional

from engine.object_registry import ObjectRegistry, SelectionRef
from engine.property_policy import decide_property_application

if TYPE_CHECKING:
    from engine.ast_mutator import ASTMutator, ASTNodeRef

logger = logging.getLogger("bisync.property_inspector")


@dataclass
class PropertySpec:
    """Data-driven property description consumed by the PropertyPanel."""

    kind: str
    name: str
    value: Any
    value_type: str
    source: str
    widget_hint: str
    section: str
    apply_strategy: str = "hot_or_ast"
    read_only: bool = False
    range_hint: Optional[tuple[float, float, float]] = None
    options: tuple[str, ...] = field(default_factory=tuple)
    owner_kind: Optional[str] = None
    owner_name: Optional[str] = None
    line_number: Optional[int] = None
    col_offset: Optional[int] = None
    param_name: Optional[str] = None
    param_index: Optional[int] = None
    value_kind: Optional[str] = None
    container_kind: Optional[str] = None
    display_key: str = ""
    param_ref: Any = None
    semantic_group: str = "generic"
    live_safe: bool = False
    source_key: Optional[str] = None
    backing_lane: str = "source"
    read_only_reason: str = ""

    @property
    def key(self) -> str:
        if self.line_number is not None and self.col_offset is not None:
            return (
                f"{self.kind}:{self.owner_kind}:{self.owner_name}:"
                f"{self.line_number}:{self.col_offset}:{self.param_name}:{self.param_index}"
            )
        return f"{self.kind}:{self.display_key or self.name}"


class PropertyInspector:
    """Discovers editable properties for the selected live object."""

    _MAX_SLIDER_ABS_VALUE = 100000.0
    _SKIP_PARAMS = {
        "self",
        "args",
        "kwargs",
        "submobjects",
        "vmobject_class",
        "arc_center",
        "sheen_factor",
        "color_scheme",
    }

    def __init__(
        self,
        ast_mutator: ASTMutator,
        object_registry: ObjectRegistry,
        scene_getter: Callable[[], Any],
    ) -> None:
        self._ast_mutator = ast_mutator
        self._object_registry = object_registry
        self._scene_getter = scene_getter

    def inspect_selection(self, selection: Optional[SelectionRef]) -> list[PropertySpec]:
        if selection is None:
            return []

        binding = (
            self._ast_mutator.get_binding_by_source_key(selection.source_key)
            if selection.source_key
            else self._ast_mutator.get_binding_by_name(selection.variable_name)
        )
        live_mobject = self._resolve_live_mobject(selection)

        constructor_specs = self._build_ast_param_specs(
            getattr(binding, "constructor_params", []),
            live_mobject,
            binding,
            section="Source Properties",
        )
        modifier_specs = self._build_call_specs(
            getattr(binding, "modifier_calls", []),
            live_mobject,
            binding,
            section="Source Chain",
        )
        animation_specs = self._build_call_specs(
            getattr(binding, "animation_calls", []),
            live_mobject,
            binding,
            section="Source Chain",
        )

        code_names = {spec.name for spec in constructor_specs + modifier_specs + animation_specs}
        live_specs = self._build_live_specs(live_mobject, code_names, binding, selection)

        return constructor_specs + modifier_specs + animation_specs + live_specs

    def _build_ast_param_specs(
        self,
        param_refs: list[ASTParamRef],
        live_mobject: Any,
        binding: SceneNodeRef | None,
        section: str,
    ) -> list[PropertySpec]:
        specs: list[PropertySpec] = []
        for param_ref in param_refs:
            spec = self._make_ast_spec(param_ref, live_mobject, binding, section)
            if spec is not None:
                specs.append(spec)
        return specs

    def _build_call_specs(
        self,
        call_refs: list[Any],
        live_mobject: Any,
        binding: SceneNodeRef | None,
        section: str,
    ) -> list[PropertySpec]:
        specs: list[PropertySpec] = []
        for call_ref in call_refs:
            for param_ref in call_ref.params:
                spec = self._make_ast_spec(param_ref, live_mobject, binding, section)
                if spec is not None:
                    specs.append(spec)
        return specs

    def _make_ast_spec(
        self,
        param_ref: ASTParamRef,
        live_mobject: Any,
        binding: SceneNodeRef | None,
        section: str,
    ) -> Optional[PropertySpec]:
        value_ref = param_ref.value_ref
        display_name = self._resolve_param_display_name(param_ref, live_mobject)
        decision = decide_property_application(
            display_name,
            widget_hint=None,
            owner_kind=param_ref.owner_kind,
            binding=binding,
        )
        display_key = self._build_display_key(param_ref, decision.display_name)

        normalized_value, value_type, widget_hint = self._normalize_ast_value(value_ref)
        if widget_hint is None:
            return None

        options: tuple[str, ...] = ()
        if widget_hint == "color":
            options = self._color_options()

        apply_strategy = self._apply_strategy_for_ast(
            param_ref=param_ref,
            display_name=display_name,
            widget_hint=widget_hint,
            live_mobject=live_mobject,
            live_safe=decision.live_safe,
            binding=binding,
        )

        range_hint = self._range_hint_for(display_name, normalized_value, param_ref.owner_kind)

        return PropertySpec(
            kind="ast_param",
            name=display_name,
            value=normalized_value,
            value_type=value_type,
            source=param_ref.owner_kind,
            widget_hint=widget_hint,
            section=section,
            apply_strategy=apply_strategy,
            range_hint=range_hint,
            options=options,
            owner_kind=param_ref.owner_kind,
            owner_name=param_ref.owner_name,
            line_number=param_ref.line_number,
            col_offset=param_ref.col_offset,
            param_name=param_ref.param_name,
            param_index=param_ref.param_index,
            value_kind=value_ref.value_kind,
            container_kind=value_ref.container_kind,
            display_key=display_key,
            param_ref=param_ref,
            semantic_group=decision.semantic_group,
            live_safe=decision.live_safe,
            source_key=binding.source_key if binding is not None else None,
            backing_lane="source",
            read_only=(
                binding is not None and binding.editability != "source_editable"
            ),
            read_only_reason=(
                binding.read_only_reason if binding is not None else ""
            ),
        )

    def _build_live_specs(
        self,
        live_mobject: Any,
        taken_names: set[str],
        binding: SceneNodeRef | None,
        selection: SelectionRef,
    ) -> list[PropertySpec]:
        if live_mobject is None:
            return []

        constructor_params = self._collect_constructor_params(live_mobject)
        candidates: dict[str, PropertySpec] = {}

        for name, default in constructor_params.items():
            if name in taken_names:
                continue
            value = self._read_candidate_value(live_mobject, name, default)
            spec = self._make_live_spec(name, value, live_mobject, binding, selection)
            if spec is not None:
                candidates[name] = spec

        for getter_name in dir(live_mobject):
            if not getter_name.startswith("get_"):
                continue

            method = getattr(live_mobject, getter_name, None)
            if method is None or not callable(method):
                continue

            prop_name = getter_name[4:]
            if prop_name in taken_names or not prop_name or prop_name.startswith("_"):
                continue

            try:
                signature = inspect.signature(method)
            except (TypeError, ValueError):
                continue

            required_params = [
                param
                for param in signature.parameters.values()
                if param.default is inspect.Parameter.empty
                and param.kind
                not in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                )
            ]
            if required_params or not self._has_live_write_path(live_mobject, prop_name, constructor_params):
                continue

            try:
                value = method()
            except Exception:
                continue

            spec = self._make_live_spec(prop_name, value, live_mobject, binding, selection)
            if spec is not None and prop_name not in candidates:
                candidates[prop_name] = spec

        if hasattr(live_mobject, "font_size") and "font_size" not in candidates and "font_size" not in taken_names:
            spec = self._make_live_spec(
                "font_size",
                getattr(live_mobject, "font_size"),
                live_mobject,
                binding,
                selection,
            )
            if spec is not None:
                candidates["font_size"] = spec

        return list(candidates.values())

    def _make_live_spec(
        self,
        name: str,
        value: Any,
        live_mobject: Any,
        binding: SceneNodeRef | None,
        selection: SelectionRef,
    ) -> Optional[PropertySpec]:
        normalized = self._normalize_live_value(value)
        if normalized is None:
            return None

        value_type = self._value_type_for(normalized)
        widget_hint = self._widget_hint_for(name, normalized)
        if widget_hint == "slider" and not self._is_slider_safe_number(normalized):
            widget_hint = "text"
        decision = decide_property_application(
            name,
            widget_hint=widget_hint,
            owner_kind="live",
            binding=binding,
        )
        options: tuple[str, ...] = ()
        if widget_hint == "color":
            options = self._color_options()

        plan_persistence = getattr(self._ast_mutator, "plan_property_persistence", None)
        persistence_strategy = (
            plan_persistence(
                selection.variable_name,
                name,
                source_key=selection.source_key,
                path=tuple(selection.path),
            )
            if selection.source_key is not None and callable(plan_persistence)
            else None
        )
        reliable_source_write = (
            persistence_strategy is not None and not persistence_strategy.no_persist
        )
        live_read_only = (
            selection.editability != "source_editable"
            or selection.source_key is None
            or decision.read_only
        )
        if live_read_only and widget_hint == "slider":
            widget_hint = "text"

        if selection.editability != "source_editable" or selection.source_key is None:
            read_only_reason = selection.read_only_reason or "live readout only"
        elif decision.read_only:
            read_only_reason = decision.reason
        else:
            read_only_reason = ""

        return PropertySpec(
            kind="live_property",
            name=name,
            value=normalized,
            value_type=value_type,
            source="live",
            widget_hint=widget_hint,
            section="Live Readout",
            apply_strategy="hot_or_ast" if decision.live_safe else "ast_reload",
            range_hint=self._range_hint_for(name, normalized, "live"),
            options=options,
            display_key=decision.display_name,
            semantic_group=decision.semantic_group,
            live_safe=decision.live_safe,
            source_key=selection.source_key,
            backing_lane="live",
            read_only=live_read_only,
            read_only_reason=read_only_reason,
        )

    def _apply_strategy_for_ast(
        self,
        *,
        param_ref: ASTParamRef,
        display_name: str,
        widget_hint: str,
        live_mobject: Any,
        live_safe: bool,
        binding: SceneNodeRef | None,
    ) -> str:
        if binding is not None and binding.editability != "source_editable":
            return "read_only"
        if param_ref.owner_kind != "constructor":
            return "ast_reload"
        if widget_hint in {"tuple", "code"}:
            return "ast_reload"
        if not live_safe:
            return "ast_reload"
        if live_mobject is None:
            return "ast_only"
        if self._has_live_write_path(live_mobject, display_name, self._collect_constructor_params(live_mobject)):
            return "hot_or_ast"
        return "ast_reload"

    def _has_live_write_path(
        self,
        mob: Any,
        prop_name: str,
        constructor_params: dict[str, Any],
    ) -> bool:
        return (
            hasattr(mob, f"set_{prop_name}")
            or hasattr(mob, prop_name)
            or prop_name in constructor_params
        )

    def _has_reliable_source_write_path(self, mob: Any, prop_name: str) -> bool:
        constructor_params = self._collect_constructor_params(mob)
        if prop_name in constructor_params:
            return True
        setter_name = f"set_{prop_name}"
        return hasattr(mob, setter_name) or hasattr(type(mob), setter_name)

    def _resolve_param_display_name(
        self,
        param_ref: ASTParamRef,
        live_mobject: Any,
    ) -> str:
        if not param_ref.param_name.startswith("arg"):
            return param_ref.param_name
        if param_ref.param_index is None:
            return param_ref.param_name

        signature_names = self._resolve_runtime_signature_names(param_ref, live_mobject)
        if param_ref.param_index < len(signature_names):
            return signature_names[param_ref.param_index]
        return param_ref.param_name

    def _resolve_runtime_signature_names(
        self,
        param_ref: ASTParamRef,
        live_mobject: Any,
    ) -> list[str]:
        signature = None

        if param_ref.owner_kind == "constructor" and live_mobject is not None:
            signature = self._safe_signature(type(live_mobject).__init__)
        elif param_ref.owner_kind == "factory_method":
            signature = None
        elif param_ref.owner_kind in {"modifier", "animate"} and live_mobject is not None:
            method = getattr(type(live_mobject), param_ref.owner_name, None)
            if method is not None:
                signature = self._safe_signature(method)
        elif param_ref.owner_kind == "animation_effect":
            try:
                import manim
                obj = getattr(manim, param_ref.owner_name, None)
                if obj is not None:
                    signature = self._safe_signature(obj)
                    if signature is None and inspect.isclass(obj):
                        signature = self._safe_signature(obj.__init__)
            except Exception:
                signature = None
        elif param_ref.owner_kind == "play":
            try:
                import manim
                signature = self._safe_signature(manim.Scene.play)
            except Exception:
                signature = None

        return self._signature_to_param_names(signature)

    def _build_display_key(self, param_ref: ASTParamRef, display_name: str) -> str:
        if param_ref.owner_kind in {"constructor", "factory_method"}:
            return display_name
        if param_ref.owner_kind == "play":
            return f"play.{display_name}"
        return f"{param_ref.scoped_owner_name}.{display_name}"

    def _normalize_ast_value(
        self,
        value_ref: ASTValueRef,
    ) -> tuple[Any, str, Optional[str]]:
        literal = value_ref.literal_value

        if value_ref.value_kind == "color" and literal is not None:
            return literal, "string", "color"
        if isinstance(literal, bool):
            return literal, "bool", "checkbox"
        if isinstance(literal, Integral) and not isinstance(literal, bool):
            normalized = int(literal)
            widget_hint = "slider" if self._is_slider_safe_number(normalized) else "text"
            return normalized, "number", widget_hint
        if isinstance(literal, Real):
            normalized = float(literal)
            if not math.isfinite(normalized):
                return value_ref.raw_code, "code", "code"
            widget_hint = "slider" if self._is_slider_safe_number(normalized) else "text"
            return normalized, "number", widget_hint
        if isinstance(literal, str):
            return literal, "string", "text"
        if (
            value_ref.value_kind == "sequence"
            and isinstance(literal, list)
            and 2 <= len(literal) <= 3
            and all(isinstance(item, (int, float)) for item in literal)
        ):
            return [float(item) if isinstance(item, Real) else item for item in literal], "tuple", "tuple"

        return value_ref.raw_code, "code", "code"

    def _collect_constructor_params(self, mob: Any) -> dict[str, Any]:
        params: dict[str, Any] = {}
        try:
            signature = inspect.signature(type(mob).__init__)
        except (TypeError, ValueError) as exc:
            return params

        for name, param in signature.parameters.items():
            if name in self._SKIP_PARAMS or name.startswith("_"):
                continue
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            params[name] = None if param.default is inspect.Parameter.empty else param.default
        return params

    def _read_candidate_value(self, mob: Any, name: str, default: Any) -> Any:
        if hasattr(mob, name):
            try:
                return getattr(mob, name)
            except Exception:
                pass

        getter_name = f"get_{name}"
        if hasattr(mob, getter_name):
            getter = getattr(mob, getter_name)
            if callable(getter):
                try:
                    return getter()
                except Exception:
                    pass
        return default

    def _resolve_live_mobject(self, selection: SelectionRef) -> Optional[Any]:
        scene = self._scene_getter()
        if scene is None:
            return None

        live_mobject = self._object_registry.find_mobject(scene, selection.mobject_id)
        if live_mobject is not None:
            return live_mobject

        if selection.source_key:
            live_mobject = self._object_registry.find_mobject_by_source_key(
                scene,
                selection.source_key,
            )
            if live_mobject is not None:
                return live_mobject

        top_level = self._object_registry.get_by_variable_name(selection.variable_name)
        if top_level is not None:
            return self._object_registry.find_mobject(scene, top_level.mobject_id)
        return None

    @classmethod
    def _normalize_live_value(cls, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, Integral):
            return int(value)
        if isinstance(value, Real):
            normalized = float(value)
            if not math.isfinite(normalized):
                return None
            return normalized
        if isinstance(value, str):
            return value
        if hasattr(value, "to_hex"):
            return cls._color_to_name(value)
        return None

    @staticmethod
    def _value_type_for(value: Any) -> str:
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, (int, float)):
            return "number"
        return "string"

    @staticmethod
    def _widget_hint_for(name: str, value: Any) -> str:
        if isinstance(value, bool):
            return "checkbox"
        if isinstance(value, str) and "color" in name:
            return "color"
        if isinstance(value, (int, float)):
            if not PropertyInspector._is_slider_safe_number(value):
                return "text"
            return "slider"
        return "text"

    @staticmethod
    def _range_hint_for(
        name: str,
        value: Any,
        owner_kind: str,
    ) -> Optional[tuple[float, float, float]]:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None

        if owner_kind == "transform" and name == "scale":
            return (0.1, 10.0, 0.1)
        if owner_kind == "transform" and name == "rotate":
            return (-math.tau, math.tau, 0.05)

        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            return None
        step = 1.0 if isinstance(value, int) else 0.1

        if "opacity" in name:
            return (0.0, 1.0, 0.01 if not isinstance(value, int) else 1.0)
        if "angle" in name or "rotate" in name:
            return (-math.tau, math.tau, 0.05)

        magnitude = abs(numeric_value)
        if magnitude == 0.0:
            minimum, maximum = (-10.0, 10.0)
        elif magnitude <= 1.0:
            minimum, maximum = (0.0, 5.0)
        elif magnitude <= 10.0:
            minimum, maximum = (-20.0, 20.0)
        elif magnitude <= 100.0:
            minimum, maximum = (0.0, 200.0)
        else:
            minimum, maximum = (0.0, magnitude * 2.0)

        if any(token in name for token in ("width", "radius", "length", "size")):
            minimum = max(0.0, minimum)

        if numeric_value < minimum:
            minimum = numeric_value - max(1.0, magnitude * 0.5)
        if numeric_value > maximum:
            maximum = numeric_value + max(1.0, magnitude * 0.5)
        if minimum == maximum:
            maximum += step
        return (minimum, maximum, step)

    @classmethod
    def _is_slider_safe_number(cls, value: Any) -> bool:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(numeric) and abs(numeric) <= cls._MAX_SLIDER_ABS_VALUE

    @classmethod
    def _color_to_name(cls, color: Any) -> Optional[str]:
        try:
            if hasattr(color, "to_hex"):
                target_hex = color.to_hex().upper()
            elif isinstance(color, str):
                target_hex = color.upper()
            else:
                return None
        except Exception:
            return None

        return cls._color_reverse_map().get(target_hex, target_hex)

    @classmethod
    def _color_options(cls) -> tuple[str, ...]:
        return tuple(sorted(set(cls._color_reverse_map().values())))

    @classmethod
    def _color_reverse_map(cls) -> dict[str, str]:
        if hasattr(cls, "_cached_color_map"):
            return cls._cached_color_map

        import manim

        color_map: dict[str, str] = {}
        for name in dir(manim):
            obj = getattr(manim, name)
            try:
                if hasattr(obj, "to_hex"):
                    color_map[obj.to_hex().upper()] = name
                elif isinstance(obj, str) and obj.startswith("#"):
                    color_map[obj.upper()] = name
            except Exception:
                continue

        cls._cached_color_map = color_map
        return color_map

    @staticmethod
    def _safe_signature(obj: Any) -> Optional[inspect.Signature]:
        try:
            return inspect.signature(obj)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _signature_to_param_names(signature: Optional[inspect.Signature]) -> list[str]:
        if signature is None:
            return []

        names: list[str] = []
        for param in signature.parameters.values():
            if param.name in {"self", "cls"}:
                continue
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            names.append(param.name)
        return names
