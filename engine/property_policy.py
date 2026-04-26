"""
Bi-Sync Property Apply Policy
=============================

Centralizes which properties are safe for in-memory live updates and which
must persist through AST save + full reload to remain semantically correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from engine.ast_mutator import SceneNodeRef


@dataclass(frozen=True)
class PropertyApplyDecision:
    """Decision shared by inspector, panel, hot-swap, and scene sync."""

    semantic_group: str
    apply_mode: str
    display_name: str
    reason: str = ""

    @property
    def live_safe(self) -> bool:
        return self.apply_mode == "live_safe"

    @property
    def reload_only(self) -> bool:
        return self.apply_mode == "reload_only"

    @property
    def read_only(self) -> bool:
        return self.apply_mode == "read_only"


_VISUAL_EXACT = {
    "color",
    "fill_color",
    "stroke_color",
    "background_stroke_color",
    "fill_opacity",
    "stroke_opacity",
    "background_stroke_opacity",
    "opacity",
    "stroke_width",
    "background_stroke_width",
}
_GEOMETRY_EXACT = {
    "radius",
    "side_length",
    "width",
    "height",
    "font_size",
    "x_length",
    "y_length",
    "depth",
}
_GEOMETRY_TOKENS = (
    "radius",
    "side_length",
    "font_size",
    "height",
    "length",
    "depth",
    "size",
    "width",
)
_SIZE_AFFECTING_METHODS = {
    "scale",
    "scale_to_fit_width",
    "scale_to_fit_height",
    "stretch",
    "stretch_to_fit_width",
    "stretch_to_fit_height",
    "set_width",
    "set_height",
    "match_width",
    "match_height",
    "rescale_to_fit",
}


def decide_property_application(
    prop_name: str,
    *,
    widget_hint: Optional[str] = None,
    owner_kind: Optional[str] = None,
    binding: Optional[SceneNodeRef] = None,
) -> PropertyApplyDecision:
    """Classify how a property should behave across preview + persistence."""

    normalized = (prop_name or "").lower()
    display_name = prop_name

    if owner_kind not in {None, "constructor", "live"}:
        return PropertyApplyDecision(
            semantic_group="code",
            apply_mode="reload_only",
            display_name=display_name,
            reason="non-constructor parameters persist via reload",
        )

    if widget_hint in {"tuple", "code"}:
        return PropertyApplyDecision(
            semantic_group="code",
            apply_mode="read_only" if owner_kind == "live" else "reload_only",
            display_name=display_name,
            reason=(
                "live readout only; complex values need an exact source-backed control"
                if owner_kind == "live"
                else "complex values persist via reload"
            ),
        )

    if is_visual_property(normalized):
        return PropertyApplyDecision(
            semantic_group="visual",
            apply_mode="live_safe",
            display_name=display_name,
        )

    if is_geometry_property(normalized):
        if owner_kind == "live":
            display_name = f"{prop_name} (effective)"
            return PropertyApplyDecision(
                semantic_group="geometry",
                apply_mode="read_only",
                display_name=display_name,
                reason="effective rendered size is read-only; edit the source-backed base value instead",
            )

        if owner_kind == "constructor":
            display_name = f"{prop_name} (base)"
            if binding_has_size_transform(binding):
                reason = "size-affecting modifiers make this a base-code value"
            else:
                reason = "geometry edits reload for correctness"
        else:
            reason = "geometry edits reload for correctness"
        return PropertyApplyDecision(
            semantic_group="geometry",
            apply_mode="reload_only",
            display_name=display_name,
            reason=reason,
        )

    if "text" in normalized:
        return PropertyApplyDecision(
            semantic_group="text",
            apply_mode="read_only" if owner_kind == "live" else "reload_only",
            display_name=display_name,
            reason=(
                "live text readout is informational; edit the source-backed text value instead"
                if owner_kind == "live"
                else "text edits persist via reload"
            ),
        )

    return PropertyApplyDecision(
        semantic_group="live_readout" if owner_kind == "live" else "code",
        apply_mode="read_only" if owner_kind == "live" else "reload_only",
        display_name=display_name,
        reason=(
            "live readout only; no reliable source-backed write path"
            if owner_kind == "live"
            else "non-visual props reload for correctness"
        ),
    )


def is_visual_property(prop_name: str) -> bool:
    normalized = (prop_name or "").lower()
    if normalized in _VISUAL_EXACT:
        return True
    if normalized.endswith("_opacity"):
        return True
    if normalized.endswith("_color"):
        return True
    if normalized.endswith("_width") and "stroke" in normalized:
        return True
    return False


def is_geometry_property(prop_name: str) -> bool:
    normalized = (prop_name or "").lower()
    if normalized in _GEOMETRY_EXACT:
        return True
    if normalized in _VISUAL_EXACT:
        return False
    return any(token in normalized for token in _GEOMETRY_TOKENS)


def binding_has_size_transform(binding: Optional[SceneNodeRef]) -> bool:
    if binding is None:
        return False

    for call_ref in getattr(binding, "modifier_calls", []):
        if call_ref.owner_name in _SIZE_AFFECTING_METHODS:
            return True
    return False
