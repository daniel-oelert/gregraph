"""GREGraph — local, Git-aware requirements management CLI.

Specification: docs/design.md (spec §16.1, §16.4).
"""

import pkgutil

__path__ = pkgutil.extend_path(__path__, __name__)

__version__ = "0.2.0"
