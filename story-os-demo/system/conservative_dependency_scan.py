"""Offline AST-based scanner for forbidden tokenizer/ML dependencies.

This scanner is deliberately conservative: any dynamic import it cannot resolve
is reported as a finding, never silently ignored.  It uses only the standard
library so it can run in the offline conservative budget environment.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


# Modules that would pull in real tokenizer/ML runtime code.  Matching is
# performed on the top-level package name (the first dotted segment).
FORBIDDEN_PROVIDER_SDK_MODULES = frozenset({
    "tokenizers",
    "transformers",
    "torch",
    "tensorflow",
    "sentence_transformers",
    "tiktoken",
    "openai",
    "anthropic",
    "huggingface_hub",
})

# Dynamic import callables that are treated as findings when their argument is
# not a literal string we can prove is safe.
_DYNAMIC_IMPORT_NAMES = frozenset({
    "__import__",
    "importlib.import_module",
    "importlib.__import__",
})


@dataclass(frozen=True)
class DependencyScanFinding:
    """One forbidden or uncertain import detected by the scanner."""

    file: str
    line: int
    module: str
    reason: str


@dataclass(frozen=True)
class DependencyScanResult:
    """Aggregate result of scanning one or more files."""

    findings: tuple[DependencyScanFinding, ...]
    scanned_files: int
    unparseable_files: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.findings and not self.unparseable_files


def _top_level(module_name: str) -> str:
    return module_name.split(".", 1)[0] if module_name else module_name


def _extract_call_name(node: ast.expr) -> str:
    """Best-effort extraction of a dotted callable name from an AST expr."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _extract_call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def scan_source(source: str, filename: str) -> Iterable[DependencyScanFinding]:
    """Yield findings for one source string.

    Raises SyntaxError if the source cannot be parsed; callers should catch
    that and treat the file as unparseable (fail closed).
    """
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = _top_level(alias.name)
                if top in FORBIDDEN_PROVIDER_SDK_MODULES:
                    yield DependencyScanFinding(
                        file=filename, line=node.lineno,
                        module=alias.name,
                        reason="forbidden-import",
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            top = _top_level(node.module)
            if top in FORBIDDEN_PROVIDER_SDK_MODULES:
                yield DependencyScanFinding(
                    file=filename, line=node.lineno,
                    module=node.module,
                    reason="forbidden-from-import",
                )
        elif isinstance(node, ast.Call):
            callee = _extract_call_name(node.func)
            if callee not in _DYNAMIC_IMPORT_NAMES:
                continue
            # Conservative: only allow a literal safe string argument.
            if not node.args:
                yield DependencyScanFinding(
                    file=filename, line=node.lineno,
                    module=callee,
                    reason="dynamic-import-no-args",
                )
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                top = _top_level(first.value)
                if top in FORBIDDEN_PROVIDER_SDK_MODULES:
                    yield DependencyScanFinding(
                        file=filename, line=node.lineno,
                        module=first.value,
                        reason="dynamic-import-forbidden",
                    )
            else:
                yield DependencyScanFinding(
                    file=filename, line=node.lineno,
                    module=callee,
                    reason="dynamic-import-non-literal",
                )


def scan_file(path: Path) -> tuple[tuple[DependencyScanFinding, ...], bool]:
    """Scan one file.  Returns (findings, parse_ok)."""
    try:
        # utf-8-sig strips a leading BOM if present; without it files
        # saved as UTF-8-with-BOM are rejected by ast.parse.
        source = path.read_text(encoding="utf-8-sig", errors="strict")
    except (OSError, UnicodeDecodeError):
        return (
            (DependencyScanFinding(
                file=str(path), line=0, module="",
                reason="unreadable-file",
            ),),
            False,
        )
    try:
        return tuple(scan_source(source, str(path))), True
    except SyntaxError:
        return (
            (DependencyScanFinding(
                file=str(path), line=0, module="",
                reason="unparseable-file",
            ),),
            False,
        )


def scan_directories(
    roots: Sequence[Path],
    *,
    exclude_globs: Sequence[str] = (),
) -> DependencyScanResult:
    """Scan all ``*.py`` files under *roots* for forbidden dependencies."""
    findings: list[DependencyScanFinding] = []
    unparseable: list[str] = []
    scanned = 0
    exclude_suffixes = tuple(exclude_globs) if exclude_globs else ()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            text = str(path)
            if any(text.endswith(suffix) for suffix in exclude_suffixes):
                continue
            file_findings, parse_ok = scan_file(path)
            scanned += 1
            if not parse_ok:
                unparseable.append(text)
            findings.extend(file_findings)
    return DependencyScanResult(
        findings=tuple(findings),
        scanned_files=scanned,
        unparseable_files=tuple(unparseable),
    )
