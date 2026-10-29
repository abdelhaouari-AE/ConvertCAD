"""
python -m convertcad            -> opens the desktop interface
python -m convertcad plan.pdf   -> opens the interface with that drawing
python -m convertcad --cli ...  -> command-line tool (see convertcad/cli.py)
"""

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from .cli import main as cli_main
        return cli_main(sys.argv[2:])
    from .ui.app import run_gui
    return run_gui(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
