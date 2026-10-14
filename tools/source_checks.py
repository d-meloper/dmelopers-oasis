"""Development-only impact selection; never installed into adopting projects."""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SMOKE = {"tests.test_public_source", "tests.test_source_delivery", "tests.test_distribution"}
DEPENDENTS = {
    "installation": {"installation", "workflow_installation", "doctor", "distribution", "skills", "gitops", "knowledge", "rpc_efficiency"},
    "doctor": {"doctor"}, "skills": {"skills", "workflow_installation", "doctor", "public_source"},
    "publication": {"publication", "build", "source_delivery", "public_source"},
    "github": {"github", "publication", "backup"},
    "build": {"build", "publication", "source_delivery"},
    "backup": {"backup", "gitops"}, "gitops": {"gitops", "backup"},
    "sessions": {"sessions", "session_transport", "deadlines", "shared_runtime", "rpc_efficiency", "notifications", "waiting", "workflows", "dependencies"},
    "shared_runtime": {"shared_runtime", "rpc_efficiency", "sessions", "session_transport", "deadlines", "notifications", "waiting", "workflows", "dependencies"},
    "notifications": {"notifications", "rpc_efficiency", "shared_runtime", "waiting", "deadlines", "workflows", "dependencies"},
    "knowledge": {"knowledge"},
    "workflows": {"workflows", "sessions", "workflow_installation", "dependencies", "notifications", "waiting", "deadlines", "shared_runtime", "rpc_efficiency"},
    "common": {"common"},
    "public_source": {"public_source", "source_delivery", "distribution"},  # Retire legacy source-only module.
}


def test_consumers(changed, texts):
    modules = {name: name[:-3].replace("/", ".").removesuffix(".__init__") for name in texts}
    known = set(modules.values()) | {name[:-3].replace("/", ".") for name in changed if name.startswith("tests/") and name.endswith(".py")}
    imports = {}
    for name, text in texts.items():
        module = modules[name]
        package = module if name.endswith("/__init__.py") else module.rpartition(".")[0]
        dependencies = imports.setdefault(module, set())
        for node in ast.walk(ast.parse(text, filename=name)):
            if isinstance(node, ast.Import):
                dependencies.update(alias.name for alias in node.names if alias.name in known)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    prefix = package.split(".")[:len(package.split(".")) - node.level + 1]
                    base = ".".join([*prefix, *([base] if base else [])])
                dependencies.update(candidate for candidate in [base, *(base + "." + alias.name for alias in node.names)] if candidate in known)
    affected = {name[:-3].replace("/", ".") for name in changed if name.startswith("tests/") and name.endswith(".py")}
    while True:
        following = affected | {module for module, dependencies in imports.items() if dependencies & affected}
        if following == affected:
            return {modules[name] for name in texts if Path(name).name.startswith("test_")} & affected
        affected = following


def select(changed, *, full=False, version_literal_only=False, fixture_consumers=(), _legacy=False, _dependents=None, _smoke=None):
    """Unknown runtime/development Python changes choose full coverage.

    Common/CLI changes can affect all modules. Expensive session and backup
    fixtures run when their inputs change, rather than on each document edit.
    """
    dependents = DEPENDENTS if _dependents is None else _dependents
    modules = set(SMOKE if _smoke is None else _smoke) | set(fixture_consumers)
    for name in changed:
        if name in {"oasis.py", "oasis_harness/cli.py", "oasis_harness/common.py"} or not _legacy and name in {"tools/source_checks.py", "tests/__init__.py"}:
            full = True
        elif name.startswith("oasis_harness/") and name.endswith(".py"):
            module = Path(name).stem
            if module == "__init__":
                if not _legacy and not version_literal_only:
                    full = True
                continue
            if module not in dependents:
                full = True
            else:
                modules.update("tests.test_" + item for item in dependents[module])
        elif name.startswith("tests/") and name.endswith(".py"):
            if Path(name).stem != "__init__" and (_legacy or Path(name).stem.startswith("test_")):
                modules.add("tests." + Path(name).stem)
        elif name.startswith("seed/") or name.startswith("library/"):
            modules.add("tests.test_skills")
        elif name == "tools/bump_commit_version.py" or name.startswith(".githooks/"):
            modules.add("tests.test_commit_version")
        elif name.startswith("tools/") and name.endswith(".py") and name not in {
                "tools/source_checks.py", "tools/source_delivery.py", "tools/source_policy.py", "tools/check_public_source.py"}:
            full = True
    return {"full": full, "modules": sorted(modules), "changed": sorted(changed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed", action="append", default=[])
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--version-literal-only", action="store_true", help="Adapter-verified before/after package literal change; attestation rechecks the bytes")
    args = parser.parse_args()
    # Compile without producing pycache or relying on Python's optimize setting.
    for folder in ("oasis_harness", "tools", "tests"):
        for path in Path(folder).glob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    texts = {path.as_posix(): path.read_text(encoding="utf-8") for path in Path("tests").glob("*.py")}
    coverage = select(args.changed, full=args.full, version_literal_only=args.version_literal_only,
                      fixture_consumers=test_consumers(args.changed, texts))
    print("Source coverage: " + ("full suite" if coverage["full"] else ", ".join(coverage["modules"])), flush=True)
    loader = unittest.TestLoader()
    suite = loader.discover("tests", top_level_dir=".") if coverage["full"] else loader.loadTestsFromNames(coverage["modules"])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
