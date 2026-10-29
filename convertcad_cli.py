"""
Console launcher of the command-line tool.

    python convertcad_cli.py plan.pdf -o plan.dxf --scale 100

It is also the entry point of ConvertCAD-cli.exe, the console program
built next to ConvertCAD.exe (see ConvertCAD.spec) for scripts and batch
files. Same options as:  python -m convertcad --cli --help

This is a COMMAND-LINE tool: it needs arguments. Double-clicked without
any, it explains how to use it and waits, instead of closing at once.
"""

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from convertcad.launcher import ensure_dependencies, pause_if_double_clicked
    if not getattr(sys, "frozen", False) and not ensure_dependencies(gui=False):
        pause_if_double_clicked()
        return 1
    from convertcad.cli import build_parser, main as cli_main
    if len(sys.argv) == 1:
        build_parser().print_help()
        print("\nThis is the command-line tool: open a command prompt and type "
              "for example\n    ConvertCAD-cli plan.pdf -o plan.dxf\n"
              "To use the application with its window, start ConvertCAD.exe "
              "(or main.py / ConvertCAD.pyw from the source code).")
        pause_if_double_clicked()
        return 2
    code = cli_main(sys.argv[1:])
    pause_if_double_clicked()
    return code


if __name__ == "__main__":
    sys.exit(main())
