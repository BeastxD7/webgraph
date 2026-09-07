"""Shared test setup.

The API blocks loopback and link-local addresses by default -- that is the point of the
control -- but this suite deliberately serves its fixtures from `127.0.0.1`, because a
stubbed fetch would test the handler and not the pipeline underneath it. Opt out for the
whole suite, the same way someone would when pointing a local API at a local site.

Set before the app's lifespan runs, so `guard.configure_from_env` sees it.
"""

from __future__ import annotations

import os

os.environ.setdefault("WEBGRAPH_ALLOW_PRIVATE_HOSTS", "1")
