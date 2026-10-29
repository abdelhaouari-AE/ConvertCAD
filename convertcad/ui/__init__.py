"""
convertcad.ui — the desktop interface (PySide6 / Qt 6).

Start it with ``python main.py`` or ``python -m convertcad``.
Entry point: convertcad.ui.app.run_gui(). The interface never converts by
itself: it fills a core.pipeline.Options object and runs the engine in a
background process (core/jobs.py).
"""
