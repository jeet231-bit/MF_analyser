"""Serve the built frontend from the same process as the API, with SPA fallback routing.

Hashed assets under ``/assets`` are cacheable for a year; ``index.html`` is never cached, so a
new build shows up on the next reload. Without a build the root answers a short page that says
how to get one, and the API keeps working."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from starlette.staticfiles import StaticFiles

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>MF Analyser</title>
<body style="font-family:system-ui;margin:3rem;color:#1b2b28">
<h1>MF Analyser API is running</h1>
<p>The web app has not been built. Run <code>npm run build</code> at the repo root and reload,
or use <code>npm run dev</code> for the development server on port 5173.</p>
<p>API docs: <a href="/api/docs">/api/docs</a> · health: <a href="/api/health">/api/health</a></p>
</body>"""


class ImmutableStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_frontend(app: FastAPI, static_dir: Path | None) -> None:
    """Register the asset mount and the catch-all after every API route."""
    if static_dir is None or not (static_dir / "index.html").exists():

        @app.get("/", include_in_schema=False)
        def not_built() -> HTMLResponse:
            return HTMLResponse(NOT_BUILT)

        return

    dist = static_dir.resolve()
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", ImmutableStaticFiles(directory=str(assets)), name="assets")
    index = dist / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        if path:
            candidate = (dist / path).resolve()
            if candidate.is_file() and dist in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-store"})
