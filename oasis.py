#!/usr/bin/env python3
"""Run the Oasis Harness package without installing it into its host repository."""
import sys
sys.dont_write_bytecode = True
from oasis_harness.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
