"""Core domain layer (spec §16.2).

Never imports from ``gregraph.cli``, never prints: returns results and
``Finding`` objects. All Git access goes through ``git.py`` via subprocess.
"""
