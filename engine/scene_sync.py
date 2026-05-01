"""
Bi-Sync Scene Sync Policy
=========================

Decides whether a scene file change can be applied as a narrow live-property
patch or whether the canvas must be fully reconstructed from source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.ast_mutator import ASTAnimationRef, ASTNodeRef


@dataclass
class SceneSyncDecision:
    """Result of comparing the previous and current AST metadata."""

    mode: str
    property_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def decide_scene_sync(
    old_bindings: dict[str, ASTNodeRef],
    new_bindings: dict[str, ASTNodeRef],
    old_animations: list[ASTAnimationRef],
    new_animations: list[ASTAnimationRef],
    can_fast_apply_property=None,
) -> SceneSyncDecision:
    """Choose between a fast property patch and a full scene reload."""

    if set(old_bindings) != set(new_bindings):
        return SceneSyncDecision(
            mode="full_reload",
            reasons=["binding set changed"],
        )

    if _animation_summaries(old_animations) != _animation_summaries(new_animations):
        return SceneSyncDecision(
            mode="full_reload",
            reasons=["animation metadata changed"],
        )

    property_updates: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []

    for var_name in sorted(new_bindings):
        old_ref = old_bindings[var_name]
        new_ref = new_bindings[var_name]

        if old_ref.constructor_name != new_ref.constructor_name:
            reasons.append(f"{var_name}: constructor changed")
            return SceneSyncDecision(mode="full_reload", reasons=reasons)
            
        if old_ref.transforms != new_ref.transforms:
            reasons.append(f"{var_name}: transforms changed")
            return SceneSyncDecision(mode="full_reload", reasons=reasons)

        if _call_summaries(getattr(old_ref, "modifier_calls", [])) != _call_summaries(getattr(new_ref, "modifier_calls", [])):
            reasons.append(f"{var_name}: source chain changed")
            return SceneSyncDecision(mode="full_reload", reasons=reasons)

        for prop_name, new_val in new_ref.properties.items():
            old_val = old_ref.properties.get(prop_name)
            if old_val != new_val:
                if callable(can_fast_apply_property) and not can_fast_apply_property(prop_name, new_val):
                    reasons.append(f"{var_name}: property '{prop_name}' requires reload")
                    return SceneSyncDecision(mode="full_reload", reasons=reasons)
                if isinstance(new_val, (list, tuple, dict)):
                    reasons.append(f"{var_name}: property '{prop_name}' is structural")
                    return SceneSyncDecision(mode="full_reload", reasons=reasons)
                property_updates.setdefault(var_name, {})[prop_name] = new_val

        for prop_name in old_ref.properties:
            if prop_name not in new_ref.properties:
                reasons.append(f"{var_name}: property '{prop_name}' removed")
                return SceneSyncDecision(mode="full_reload", reasons=reasons)

    return SceneSyncDecision(
        mode="property_only",
        property_updates=property_updates,
        reasons=reasons,
    )


def _animation_summaries(animation_refs: list[ASTAnimationRef]) -> tuple[Any, ...]:
    def _hashable_val(val: Any) -> Any:
        if isinstance(val, list):
            return tuple(_hashable_val(v) for v in val)
        if isinstance(val, dict):
            return tuple(sorted((k, _hashable_val(v)) for k, v in val.items()))
        return val

    return tuple(
        (
            ref.target_var,
            ref.method_name,
            _hashable_val(ref.args),
            _hashable_val(ref.kwargs),
        )
        for ref in animation_refs
    )


def _call_summaries(call_refs: list[Any]) -> tuple[Any, ...]:
    def _param_value(param: Any) -> Any:
        value_ref = getattr(param, "value_ref", None)
        literal = getattr(value_ref, "literal_value", None)
        raw = getattr(value_ref, "raw_code", "")
        if isinstance(literal, list):
            literal = tuple(literal)
        return (getattr(param, "param_name", ""), literal, raw)

    return tuple(
        (
            getattr(ref, "owner_kind", ""),
            getattr(ref, "owner_name", ""),
            tuple(_param_value(param) for param in getattr(ref, "params", [])),
        )
        for ref in call_refs
    )
