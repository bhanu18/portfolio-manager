"""Deprecated: use scripts/import_trades.py.

Kept so existing commands keep working. Forces the Yahoo Finance parser.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from import_trades import main

if __name__ == "__main__":
    print("NOTE: import_csv.py is deprecated; use scripts/import_trades.py", file=sys.stderr)
    if "--broker" not in sys.argv:
        sys.argv += ["--broker", "yahoo"]
    main()
