"""Optional loopback web UI for GREGraph (design §21).

Public interface: :func:`gregraph.webui.app.create_app` and
:func:`gregraph.webui.launch.launch`. The ``gregraph.serve`` entry point ``webui``
names ``launch``. Only the CLI imports this package, and only after ``serve``
was selected.
"""
