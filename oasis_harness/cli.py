"""One explicit command entry point; importing the package performs no work."""
import argparse
import importlib
import json
import sys

from . import __version__
from .common import HarnessError


def main(argv=None):
    parser = argparse.ArgumentParser(prog="oasis", description="Oasis Harness: explicit project operations and evidence")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("installation", "gitops", "backup", "sessions", "workflows", "publication", "build", "knowledge", "skills", "doctor"):
        module = importlib.import_module("." + name, __package__)
        module.register(commands)
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        if result is not None:
            # ASCII JSON preserves Unicode values while remaining writable to
            # redirected legacy Windows consoles. Reporting must not turn an
            # already completed operation into a misleading encoding failure.
            print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (HarnessError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
