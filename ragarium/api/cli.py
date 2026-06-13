from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("RAGARIUM_HOST", "127.0.0.1")
    port = int(os.environ.get("RAGARIUM_PORT", "8000"))
    reload_enabled = os.environ.get("RAGARIUM_RELOAD", "").lower() in {
        "1",
        "true",
        "yes",
    }
    uvicorn.run("ragarium.api.app:app", host=host, port=port, reload=reload_enabled)
