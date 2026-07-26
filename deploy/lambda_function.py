"""AWS Lambda entrypoint for qmstrace.

A single Lambda serves everything behind a Function URL:

* the API (the FastAPI app) is mounted under ``/api``, matching the frontend's
  request base;
* the built React SPA is served as static files at ``/``.

SQLite lives in the read-only deployment package, so at cold start we copy the
pre-seeded database to ``/tmp`` (the only writable location on Lambda) and point
the app at it. Writes made while a container is warm survive for that
container's lifetime only, fine for a demo, and reads are always correct.
"""

from __future__ import annotations

import os
import pathlib
import shutil

_HERE = pathlib.Path(__file__).resolve().parent
_DB_SOURCE = _HERE / "seed.db"
_DB_RUNTIME = "/tmp/qmstrace.db"

if not os.path.exists(_DB_RUNTIME):
    shutil.copy(_DB_SOURCE, _DB_RUNTIME)
os.environ["QMSTRACE_DATABASE_URL"] = f"sqlite:///{_DB_RUNTIME}"

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from mangum import Mangum  # noqa: E402

from app.main import app as api_app  # noqa: E402

root = FastAPI(docs_url=None, redoc_url=None)
root.mount("/api", api_app)
root.mount("/", StaticFiles(directory=str(_HERE / "web"), html=True), name="spa")

handler = Mangum(root)
