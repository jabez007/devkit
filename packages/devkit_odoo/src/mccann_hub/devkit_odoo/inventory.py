"""Bounded addon discovery with explicit scan coverage, independent of completeness claims."""

from dataclasses import dataclass, field
from pathlib import Path

from mccann_hub.devkit.contracts import Context, DevkitError, JSONObject
from mccann_hub.devkit_odoo.dependencies import MODULE_NAME
from mccann_hub.devkit_odoo.validation import checkpoint, contained


@dataclass
class Inventory:
    modules: dict[str, Path] = field(default_factory=dict)
    paths: list[JSONObject] = field(default_factory=list)

    def coverage(self, policy: JSONObject, *, scan_complete: bool = True) -> JSONObject:
        return {
            **policy,
            "basis": "explicit_claim"
            if policy["complete"] or policy["complete_prefixes"]
            else "incomplete_by_default",
            "scan_complete": scan_complete,
            "paths": self.paths,
            "module_count": len(self.modules),
            "resolution_basis": "manifest_presence",
            "limits": {"entries": 10000, "modules": 1000},
        }


def scan(context: Context, paths: list[str], inventory: Inventory) -> None:
    inspected = 0
    for relative in paths:
        checkpoint(context)
        try:
            root = contained(context.project_root, relative)
        except (ValueError, RuntimeError) as exc:
            raise DevkitError("INVALID_ADDONS", f"Unsafe addons path {relative!r}: {exc}") from exc
        before = len(inventory.modules)
        try:
            for child in root.iterdir():
                checkpoint(context)
                inspected += 1
                if inspected > 10000:
                    raise DevkitError(
                        "INVENTORY_LIMIT",
                        "Inventory exceeds 10000 directory entries; narrow addons_paths",
                    )
                _add_module(child, context.project_root, inventory.modules)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise DevkitError(
                "MISSING_ADDONS",
                f"Addons directory {relative!r} is unavailable; correct addons_paths",
            ) from exc
        except OSError as exc:
            raise DevkitError(
                "INVENTORY_UNAVAILABLE",
                f"Cannot inspect addons directory {relative!r}; check access",
            ) from exc
        inventory.paths.append({"path": relative, "module_count": len(inventory.modules) - before})


def _add_module(child: Path, project: Path, modules: dict[str, Path]) -> None:
    try:
        resolved = child.resolve()
    except RuntimeError as exc:
        raise DevkitError("INVALID_ADDONS", f"Addon symlink loop: {child.name!r}") from exc
    if not resolved.is_relative_to(project):
        raise DevkitError("INVALID_ADDONS", f"Addon path escapes the workspace: {child.name!r}")
    if not (child / "__manifest__.py").is_file():
        return
    if MODULE_NAME.fullmatch(child.name) is None:
        raise DevkitError(
            "INVALID_ADDONS", f"Unsafe addon path or invalid module name: {child.name!r}"
        )
    if child.name in modules:
        previous = modules[child.name].relative_to(project).as_posix()
        current = child.relative_to(project).as_posix()
        raise DevkitError(
            "INVALID_ADDONS",
            f"Duplicate addon {child.name!r}: {previous!r} and {current!r}; "
            "remove one inventory entry",
        )
    if len(modules) >= 1000:
        raise DevkitError("INVENTORY_LIMIT", "Inventory exceeds 1000 modules; narrow addons_paths")
    modules[child.name] = resolved
