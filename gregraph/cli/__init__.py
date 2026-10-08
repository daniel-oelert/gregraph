"""Command-line layer (spec §13, §16.1–16.2).

Thin: parse arguments → call one ``core.operations`` function → format output.
Never touches the filesystem directly.
"""
