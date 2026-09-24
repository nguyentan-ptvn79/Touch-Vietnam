from __future__ import annotations

import os
import sys
from pathlib import Path

from app.shared.env import load_env_file

ROOT = Path(__file__).resolve().parent

load_env_file(ROOT / ".env")
sys.path = [str(ROOT)] + [
    item for item in sys.path if item and str(Path(item).resolve()) != str(ROOT)
]

from app.shared.settings import get_settings  # noqa: E402 - load environment before app imports
from app.web.app import create_app  # noqa: E402

try:
    from waitress import serve
except ImportError:  # pragma: no cover
    serve = None


def run() -> None:
    settings = get_settings()
    app = create_app()
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "5000"))
    threads = int(os.getenv("APP_THREADS", "8"))

    if settings.environment == "production" and serve is not None:
        serve(app, host=host, port=port, threads=threads)
        return

    app.run(
        host=host,
        port=port,
        debug=settings.debug,
        use_reloader=settings.debug,
    )


if __name__ == "__main__":
    run()
