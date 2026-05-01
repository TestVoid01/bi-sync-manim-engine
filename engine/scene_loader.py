from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any, Optional


def module_name_from_path(
    scene_file: str | Path,
    *,
    project_root: str | Path,
) -> str:
    scene_path = Path(scene_file).resolve()
    root = Path(project_root).resolve()

    try:
        relative = scene_path.relative_to(root)
    except ValueError:
        return scene_path.stem

    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else scene_path.stem


def import_scene_module(module_name: str) -> ModuleType:
    return importlib.import_module(module_name)


def discover_scene_class(
    container: ModuleType | dict[str, Any],
    *,
    preferred_name: Optional[str] = None,
):
    from manim import Scene as BaseScene

    if isinstance(container, ModuleType):
        namespace = vars(container)
        owner_module = container.__name__
    else:
        namespace = container
        owner_module = str(namespace.get("__name__", "__main__"))

    if preferred_name:
        preferred = namespace.get(preferred_name)
        if _is_local_scene_subclass(preferred, owner_module, BaseScene):
            return preferred

    chosen = None
    for _, obj in namespace.items():
        if _is_local_scene_subclass(obj, owner_module, BaseScene):
            chosen = obj

    return chosen


def discover_scene_class_from_source(
    source_text: str,
    *,
    scene_file: str | Path,
    module_name: str,
    preferred_name: Optional[str] = None,
):
    compiled = compile(source_text, str(scene_file), "exec")
    namespace: dict[str, Any] = {"__name__": module_name}
    exec("from manim import *", namespace)
    exec(compiled, namespace)
    return discover_scene_class(namespace, preferred_name=preferred_name)


def discover_scene_class_from_file(
    scene_file: str | Path,
    *,
    module_name: str,
    preferred_name: Optional[str] = None,
):
    source_text = Path(scene_file).read_text(encoding="utf-8")
    return discover_scene_class_from_source(
        source_text,
        scene_file=scene_file,
        module_name=module_name,
        preferred_name=preferred_name,
    )


def _is_local_scene_subclass(obj: Any, owner_module: str, base_scene: type) -> bool:
    return (
        isinstance(obj, type)
        and issubclass(obj, base_scene)
        and obj is not base_scene
        and getattr(obj, "__module__", None) == owner_module
    )
