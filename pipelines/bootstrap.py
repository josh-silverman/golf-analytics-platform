"""Deprecated shim — the bootstrap now lives in ``app.cli.bootstrap``.

Kept so existing references keep working. The canonical, container-runnable
command is:

    docker compose exec api uv run python -m app.cli.bootstrap
    # or, from the backend directory:
    cd backend && uv run python -m app.cli.bootstrap

This module simply re-exports that entrypoint. It requires the backend ``app``
package to be importable (run it from the ``backend`` directory).
"""

from __future__ import annotations

from app.cli.bootstrap import main

if __name__ == "__main__":
    main()
