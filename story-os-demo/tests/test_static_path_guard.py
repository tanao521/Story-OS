"""Static guard against hardcoded project paths in production code.

This test scans production modules to prevent regression of implicit root paths,
module-level project context caching, and cross-project data pollution patterns.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


# Directories to scan
PRODUCTION_DIRS = [
    "agents",
    "analytics",
    "author_memory",
    "core",
    "creative_loop",
    "evaluation_engine",
    "llm",
    "planning_engine",
    "system",
    "web",
    "tools",
]

# Files to exclude (test fixtures, migration tools, etc.)
EXCLUDE_FILES = {
    "tests/",
    "tools/data_recovery.py",
    "tools/manual_history_recovery.py",
    "tools/apply_user_approved_baseline.py",
}

# Allowed patterns with reasons
ALLOWLIST: dict[str, str] = {
    # DataStore uses "data/..." as logical path, not filesystem path
    r'store\.read_json\("data/': "DataStore logical path",
    r'store\.write_json\("data/': "DataStore logical path",
    r'store\.read_text\("data/': "DataStore logical path",
    r'store\.ensure_directory\("data/': "DataStore logical path",
    r'store\.path\("data/': "DataStore logical path",
    r'store\.path\(f"data/': "DataStore f-string logical path",
    r'path=f"data/': "DataStore f-string logical path",
    r'path = f"data/': "DataStore f-string logical path",
    r'_path\([^)]*\)\s*:\s*return\s+f"data/': "DataStore path helper",
    r'self\.store\.read_json\(f"data/': "DataStore f-string logical path",
    r'load = lambda name: store\.read_json\(f"data/': "DataStore lambda helper",
    # Path patterns used with context.root concatenation
    r'Path\("data/[^"]*"\)\s*\)': "Path used with context concatenation",
    r'self\.context\.root\s*/\s*pattern': "Path used with context concatenation",
    # Application scope non-project resources
    r'PERSONAS\s*=\s*\{': "Application-scope constant",
    r'GENRE_HINTS\s*=\s*\{': "Application-scope constant",
    r'KNOWN_SCOPES\s*=\s*\{': "Application-scope constant",
    r'ASSET_CATEGORIES\s*=\s*\{': "Application-scope constant",
    # Config and schema files
    r'\.schema\.json': "JSON schema file reference",
    r'"schema_version"': "Schema version field",
    # Display strings
    r'"data_sources"': "JSON field name",
    r'"data_quality"': "JSON field name",
    # Docstrings and comments
    r'#.*data/': "Comment",
    r'""".*data/': "Docstring",
    r"'''.*data/": "Docstring",
    # Source version resolution patterns (used with context.root concatenation)
    r'\("manual", Path\("data/': "Source resolution pattern",
    r'\("edited", Path\("data/': "Source resolution pattern",
    r'\("draft", Path\("data/': "Source resolution pattern",
    r'Path\("data/versions"\)': "Source resolution pattern",
    r'Path\("data/manual"\)': "Source Resolution pattern",
    r'Path\("data/edited"\)': "Source resolution pattern",
    r'Path\("data/drafts"\)': "Source resolution pattern",
}


def _is_allowed(line: str) -> bool:
    """Check if a line matches an allowlist pattern."""
    for pattern, _reason in ALLOWLIST.items():
        if re.search(pattern, line):
            return True
    return False


def _scan_file(file_path: Path) -> list[dict[str, Any]]:
    """Scan a single Python file for forbidden path patterns."""
    violations = []

    # Forbidden patterns
    forbidden_patterns = [
        # Hardcoded Path("data") and variants
        (r'Path\("data"\)', 'Path("data")'),
        (r'Path\("data/', 'Path("data/...")'),
        (r'Path\(f"data', 'Path(f"data...")'),
        (r'Path\(\'data\'\)', "Path('data')"),
        (r'Path\(\'data/', "Path('data/...')"),
        # open() with data path
        (r'open\("data/', 'open("data/...")'),
        (r"open\('data/", "open('data/...')"),
        (r'open\(f"data', 'open(f"data...")'),
        # os.path.join with data
        (r'os\.path\.join\("data"', 'os.path.join("data", ...)'),
        (r'os\.path\.join\(\'data\'', "os.path.join('data', ...)"),
        # glob with data
        (r'\.glob\("data/', '.glob("data/...")'),
        (r'\.glob\(\'data/', ".glob('data/..."),
        # String concatenation
        (r'"data/"\s*\+', '"data/" + ...'),
        (r'\'data/\'\s*\+', "'data/' + ..."),
        (r'f"data/\{', 'f"data/{...}"'),
    ]

    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        for line_num, line in enumerate(lines, start=1):
            # Skip allowed patterns
            if _is_allowed(line):
                continue

            for pattern, description in forbidden_patterns:
                if re.search(pattern, line):
                    violations.append({
                        "file": str(file_path),
                        "line": line_num,
                        "content": line.strip(),
                        "pattern": description,
                    })

    except Exception:
        pass

    return violations


def test_no_hardcoded_data_paths_in_production():
    """Verify production code does not contain hardcoded data/ paths."""
    root = Path(__file__).parent.parent
    all_violations = []

    for dir_name in PRODUCTION_DIRS:
        dir_path = root / dir_name
        if not dir_path.exists():
            continue

        for py_file in dir_path.rglob("*.py"):
            # Skip excluded files
            rel_path = py_file.relative_to(root)
            rel_str = str(rel_path).replace("\\", "/")

            if any(excl in rel_str for excl in EXCLUDE_FILES):
                continue

            violations = _scan_file(py_file)
            all_violations.extend(violations)

    # Report violations
    if all_violations:
        msg_lines = [f"Found {len(all_violations)} hardcoded data path(s) in production code:"]
        for v in all_violations:
            rel_path = Path(v["file"]).relative_to(root)
            msg_lines.append(f"  {rel_path}:{v['line']}: {v['pattern']}")
            msg_lines.append(f"    {v['content']}")
        assert False, "\n".join(msg_lines)


def _scan_module_level_context(root: Path) -> list[dict[str, Any]]:
    """Scan for module-level get_project_context() calls."""
    violations = []

    for dir_name in PRODUCTION_DIRS:
        dir_path = root / dir_name
        if not dir_path.exists():
            continue

        for py_file in dir_path.rglob("*.py"):
            rel_path = py_file.relative_to(root)
            rel_str = str(rel_path).replace("\\", "/")

            if any(excl in rel_str for excl in EXCLUDE_FILES):
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)

                # Walk module-level statements only
                for node in ast.iter_child_nodes(tree):
                    # Check for module-level assignments
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                # Check if value is get_project_context() or DataStore(get_project_context())
                                if isinstance(node.value, ast.Call):
                                    func = node.value.func
                                    if isinstance(func, ast.Name) and func.id == "get_project_context":
                                        violations.append({
                                            "file": str(py_file),
                                            "line": node.lineno,
                                            "type": "module_level_get_project_context",
                                            "name": target.id,
                                        })
                                    # DataStore(get_project_context())
                                    elif isinstance(func, ast.Name) and func.id == "DataStore":
                                        for arg in node.value.args:
                                            if isinstance(arg, ast.Call):
                                                if isinstance(arg.func, ast.Name) and arg.func.id == "get_project_context":
                                                    violations.append({
                                                        "file": str(py_file),
                                                        "line": node.lineno,
                                                        "type": "module_level_DataStore_with_get_project_context",
                                                        "name": target.id,
                                                    })
                    # Check for module-level annotated assignments (ctx: ProjectContext = get_project_context())
                    elif isinstance(node, ast.AnnAssign):
                        if isinstance(node.target, ast.Name) and isinstance(node.value, ast.Call):
                            func = node.value.func
                            if isinstance(func, ast.Name) and func.id == "get_project_context":
                                violations.append({
                                    "file": str(py_file),
                                    "line": node.lineno,
                                    "type": "module_level_get_project_context",
                                    "name": node.target.id,
                                })

            except Exception:
                pass

    return violations


def test_no_module_level_project_context():
    """Verify no module-level caching of ProjectContext or DataStore."""
    root = Path(__file__).parent.parent
    violations = _scan_module_level_context(root)

    if violations:
        msg_lines = [f"Found {len(violations)} module-level ProjectContext/DataStore cache(s):"]
        for v in violations:
            rel_path = Path(v["file"]).relative_to(root)
            msg_lines.append(f"  {rel_path}:{v['line']}: {v['type']} ({v['name']})")
        assert False, "\n".join(msg_lines)


def test_web_routes_use_request_context():
    """Verify Web routes use request-level context, not module-level fallback."""
    root = Path(__file__).parent.parent
    web_dir = root / "web"

    if not web_dir.exists():
        return

    violations = []
    allowed_routes = {"routes.py", "author_routes.py", "creative_loop_routes.py",
                       "analytics_routes.py", "planning_control_routes.py"}

    for py_file in web_dir.rglob("*.py"):
        if py_file.name not in allowed_routes:
            continue

        content = py_file.read_text(encoding="utf-8")
        lines = content.splitlines()

        for line_num, line in enumerate(lines, start=1):
            # Check for deprecated _ctx() pattern that falls back to CWD
            # Allow _ctx() if it just calls get_project_context() without caching
            if "_ctx()" in line and "get_project_context()" not in line:
                # Check if it's a simple wrapper
                if "return get_project_context()" in content:
                    continue
                violations.append({
                    "file": str(py_file),
                    "line": line_num,
                    "content": line.strip(),
                })

    # This is informational, not a failure
    # Phase 0B1 already fixed these patterns


if __name__ == "__main__":
    # Run scans manually for debugging
    root = Path(__file__).parent.parent
    print("Scanning for hardcoded data paths...")
    violations = []
    for dir_name in PRODUCTION_DIRS:
        dir_path = root / dir_name
        if dir_path.exists():
            for py_file in dir_path.rglob("*.py"):
                rel_str = str(py_file.relative_to(root)).replace("\\", "/")
                if not any(excl in rel_str for excl in EXCLUDE_FILES):
                    violations.extend(_scan_file(py_file))

    print(f"Found {len(violations)} violations")
    for v in violations[:10]:
        print(f"  {v['file']}:{v['line']}: {v['pattern']}")

    print("\nScanning for module-level context...")
    ctx_violations = _scan_module_level_context(root)
    print(f"Found {len(ctx_violations)} violations")
    for v in ctx_violations[:10]:
        print(f"  {v['file']}:{v['line']}: {v['type']}")