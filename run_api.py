from __future__ import annotations

import os
import site
import sys
from pathlib import Path

from app.shared.env import load_env_file

ROOT = Path(__file__).resolve().parent

load_env_file(ROOT / ".env")


def add_if_accessible(path: Path) -> None:
    if not path.exists():
        return
    try:
        if path.is_dir():
            next(path.iterdir(), None)
    except OSError:
        return
    sys.path.insert(0, str(path))


add_if_accessible(ROOT / ".python_packages")
add_if_accessible(Path(site.getusersitepackages()))
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402 - bootstrap dependency paths before importing the server

if __name__ == "__main__":
    uvicorn.run(
        "app.api.main:app",
        host=os.getenv("APP_API_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_API_PORT", "8000")),
        reload=False,
    )
