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
    "installation": {"installation", "workflow_installation", "doctor", "distribution"},
    "doctor": {"doctor"}, "skills": {"skills", "workflow_installation", "doctor", "public_source"},
    "publication": {"publication", "build", "source_delivery", "public_source"},
    "github": {"github", "publication", "backup"},
    "build": {"build", "publication", "source_delivery"},
    "backup": {"backup", "gitops"}, "gitops": {"gitops", "backup"},
    "sessions": {"sessions", "session_transport", "workflows", "dependencies"}, "knowledge": {"knowledge"},
    "workflows": {"workflows", "sessions", "workflow_installation", "dependencies"},
    "common": {"common"},
    "public_source": {"public_source", "source_delivery", "distribution"},  # Retire legacy source-only module.
}


def select(changed, *, full=False):
    """Unknown runtime/development Python changes choose full coverage.

    Common/CLI changes can affect all modules. Expensive session and backup
    fixtures run when their inputs change, rather than on each document edit.
    """
    modules = set(SMOKE)
    for name in changed:
        if name in {"oasis.py", "oasis_harness/cli.py", "oasis_harness/common.py"}:
            full = True
        elif name.startswith("oasis_harness/") and name.endswith(".py"):
            module = Path(name).stem
            if module == "__init__":
                continue  # Hook-generated patch literal; smoke checks its syntax.
            if module not in DEPENDENTS:
                full = True
            else:
                modules.update("tests.test_" + item for item in DEPENDENTS[module])
        elif name.startswith("tests/") and name.endswith(".py"):
            if Path(name).stem != "__init__":
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
    args = parser.parse_args()
    # Compile without producing pycache or relying on Python's optimize setting.
    for folder in ("oasis_harness", "tools", "tests"):
        for path in Path(folder).glob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    coverage = select(args.changed, full=args.full)
    print("Source coverage: " + ("full suite" if coverage["full"] else ", ".join(coverage["modules"])), flush=True)
    loader = unittest.TestLoader()
    suite = loader.discover("tests", top_level_dir=".") if coverage["full"] else loader.loadTestsFromNames(coverage["modules"])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
