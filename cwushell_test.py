"""Checkout script entry point; requires the installed cwushell-test package."""

import sys
from importlib.machinery import PathFinder
from importlib.util import module_from_spec
from pathlib import Path

script_directory = Path(__file__).resolve().parent
package_search = [
    entry for entry in sys.path if Path(entry).resolve() != script_directory
]

if __name__ == "__main__":
    # Keep this same-named script from shadowing the installed package.
    sys.path = package_search
    from cwushell_test.cli import main

    raise SystemExit(main())
else:
    # Imports from the checkout must still return the installed package, with
    # its normal initialization and submodule lookup (no source-path override).
    spec = PathFinder.find_spec(__name__, package_search)
    if spec is None or spec.loader is None or spec.submodule_search_locations is None:
        raise ImportError("Install cwushell-test first (task setup in the checkout)")
    package = module_from_spec(spec)
    sys.modules[__name__] = package
    spec.loader.exec_module(package)
