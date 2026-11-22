"""Pytest path setup — points the suite at the PRODUCTION source tree.

This previously prepended backend/runtime_engine, which is why the suite
validated the backend/ copies while production ran the src/ ones. Those copies
had already drifted: src/runtime_engine/runtime_api.py was 58 lines ahead (it
carries the FastAPI router and rate limiting that backend/ never got), so a
green suite said nothing about the code actually serving requests. The
duplicate packages are gone; this now wires src/.

Three entries, because the modules are written to work both ways:

  src/                 `import review_engine` / `import runtime_engine` / `import app`
                       — the package-style imports src/app.py itself uses.
  src/runtime_engine/  flat `import execution_policy` / `from runtime_api import ...`
  src/review_engine/   flat `from review_engine import review_response`

The flat entries matter because each module tries a package import first and
falls back to a flat one; production satisfies the flat form by running with
WORKDIR=/app/src. Reproducing both here keeps the test import environment
equivalent to production rather than merely sufficient to pass.

src/ is itself a package (src/__init__.py exists), so pytest's basedir walk
inserts the repo root rather than src/ — which is why this has to be explicit.
"""

import os
import sys

ROOT = os.path.dirname(__file__)

for _rel in (
    os.path.join('src'),
    os.path.join('src', 'runtime_engine'),
    os.path.join('src', 'review_engine'),
):
    _path = os.path.join(ROOT, _rel)
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)
