"""Bounded relative-import traversal without executing addon Python code."""

import ast
from collections.abc import Callable, Iterator
from pathlib import Path

from mccann_hub.devkit.contracts import DevkitError
from mccann_hub.devkit_odoo.file_inspection import FileBudget

LIMITS = {"files": 1000, "file_bytes": 1_048_576, "total_bytes": 16_777_216}


class PythonImports:
    """Reachable Python sources; incomplete traversal cannot establish absent models."""

    def __init__(self, module: Path, checkpoint: Callable[[], None]) -> None:
        self.root = module.resolve()
        self.budget = FileBudget("PYTHON", LIMITS, checkpoint)
        self.complete = True
        self.pending: list[Path] = []
        self.seen: set[Path] = set()
        self._enqueue(self.root / "__init__.py", required=False)

    def sources(self) -> Iterator[tuple[str, ast.Module]]:
        while self.pending:
            path = self.pending.pop()
            try:
                tree = ast.parse(self.budget.read(path))
            except (OSError, SyntaxError, ValueError, RecursionError):
                self.complete = False
                continue
            except DevkitError as exc:
                if exc.reason != "PYTHON_LIMIT":
                    raise
                self.complete = False
                return
            self._imports(path, tree)
            yield path.relative_to(self.root).as_posix(), tree

    def _enqueue(self, path: Path, *, required: bool = True) -> None:
        try:
            path = path.resolve()
            if not path.is_relative_to(self.root):
                self.complete = False
            elif path.is_file():
                if path not in self.seen:
                    self.seen.add(path)
                    self.pending.append(path)
            elif required:
                self.complete = False
        except (OSError, RuntimeError):
            self.complete = False

    def _imports(self, path: Path, tree: ast.Module) -> None:
        dynamic = {"__import__", "exec", "eval", "import_module"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "importlib":
                dynamic.update(a.asname or a.name for a in node.names if a.name == "import_module")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                if node in tree.body:
                    self._relative_import(path, node)
                else:
                    # Conditional and deferred imports do not establish registration.
                    self.complete = False
            elif isinstance(node, ast.Call) and _dynamic_call(node.func, dynamic):
                self.complete = False
            elif _absolute_addon_import(node, self.root.name):
                self.complete = False

    def _relative_import(self, path: Path, node: ast.ImportFrom) -> None:
        package = path.parent
        for _ in range(node.level - 1):
            package = package.parent
        if not package.is_relative_to(self.root):
            self.complete = False
            return
        for part in node.module.split(".") if node.module else ():
            package /= part
            if not self._module(package):
                return
        for alias in node.names:
            if alias.name == "*":
                self.complete = False
            else:
                self._module(package / alias.name)

    def _module(self, path: Path) -> bool:
        """Load package initializers before their children; a file has no submodules."""
        if path.is_dir():
            self._enqueue(path / "__init__.py", required=False)
            return True
        self._enqueue(path.with_suffix(".py"))
        return False


def _dynamic_call(function: ast.expr, names: set[str]) -> bool:
    return (isinstance(function, ast.Name) and function.id in names) or (
        isinstance(function, ast.Attribute) and function.attr in {"import_module", "__import__"}
    )


def _absolute_addon_import(node: ast.AST, addon: str) -> bool:
    names = []
    if isinstance(node, ast.ImportFrom):
        names = [node.module or ""]
    elif isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    roots = (f"odoo.addons.{addon}", f"openerp.addons.{addon}")
    return any(name == root or name.startswith(root + ".") for name in names for root in roots)
