"""Stage 2: PySide6 desktop GUI for Lender Package Builder.

This package is a presentation layer only -- it calls the Stage 1
engine (`lender_package_builder.cli.build_package`) directly and never
duplicates or reimplements processing logic. See `main_window.py` for
the top-level wiring and `worker.py` for how the engine is run off the
Qt UI thread.
"""
