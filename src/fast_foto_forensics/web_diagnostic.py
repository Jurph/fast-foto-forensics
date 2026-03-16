"""Local diagnostic web UI for single-image end-to-end runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from fast_foto_forensics.diagnostic_runner import (
    DiagnosticRequest,
    DiagnosticResult,
    _fetch_remote_image_bytes,
    run_diagnostic_request,
)
from fast_foto_forensics.export_fixture import export_diagnostic_fixture
from fast_foto_forensics.search import DDGSSearchProvider, SearchProvider
from fast_foto_forensics.synthesis import OllamaDatasheetSynthesisBackend, SynthesisBackend
from fast_foto_forensics.vision import OllamaVisionBackend, VisionBackend


class UrlDiagnosticRequest(BaseModel):
    """Request body for URL-based diagnostics."""

    image_url: str


class ExportRequest(BaseModel):
    """Request body for explicit fixture export."""

    export_token: str
    analyst_note: str = ""


@dataclass(slots=True)
class CachedDiagnosticCase:
    """Ephemeral in-memory case data for later export."""

    request: DiagnosticRequest
    result: DiagnosticResult


_PAGE_HTML = """\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Fast Foto Forensics Diagnostic</title>
    <style>
      body { font-family: Georgia, serif; margin: 2rem auto; max-width: 920px; padding: 0 1rem; }
      .dropzone { border: 2px dashed #666; padding: 1rem; background: #f5f1e8; }
      .row { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
      input[type="url"] { min-width: 24rem; flex: 1; }
      pre, textarea { width: 100%; box-sizing: border-box; }
      pre { background: #f7f7f7; padding: 0.75rem; overflow: auto; white-space: pre-wrap; }
      img { max-width: 100%; border: 1px solid #ccc; }
      button { padding: 0.5rem 0.9rem; }
      .muted { color: #555; }
    </style>
  </head>
  <body>
    <h1>Fast Foto Forensics Diagnostic</h1>
    <p class="muted">Real end-to-end pipeline wrapper. No saved run unless you click Export.</p>
    <div class="dropzone">
      <div class="row">
        <input id="fileInput" type="file" accept="image/*">
        <button id="uploadButton" type="button">Run Uploaded Image</button>
      </div>
      <p>or paste an image URL</p>
      <div class="row">
        <input id="urlInput" type="url" placeholder="https://example.com/image.jpg">
        <button id="urlButton" type="button">Run Image URL</button>
      </div>
    </div>
    <hr>
    <h2>Source Preview</h2>
    <img id="sourcePreview" alt="Source preview">
    <hr>
    <h2>Live Log</h2>
    <pre id="liveLog"></pre>
    <hr>
    <h2>Vision JSON</h2>
    <pre id="visionJson"></pre>
    <hr>
    <h2>Vision Summary</h2>
    <pre id="visionSummary"></pre>
    <hr>
    <h2>Query Plan</h2>
    <pre id="queryPlan"></pre>
    <hr>
    <h2>Search Hits</h2>
    <pre id="searchHits"></pre>
    <hr>
    <h2>Datasheet JSON</h2>
    <pre id="datasheetJson"></pre>
    <hr>
    <h2>Rendered Datasheet</h2>
    <pre id="renderedDatasheet"></pre>
    <hr>
    <h2>Failures</h2>
    <pre id="failures"></pre>
    <hr>
    <h2>Export</h2>
    <div class="row">
      <textarea
        id="analystNote"
        rows="3"
        placeholder="Notes about the failure mode or why this should become a retry fixture"
      ></textarea>
      <button id="exportButton" type="button">Export</button>
    </div>
    <pre id="exportResult"></pre>
    <script>
      let currentExportToken = null;
      let currentPreviewUrl = "";

      function renderResult(payload) {
        currentExportToken = payload.export_token || null;
        currentPreviewUrl = payload.source_preview_url || "";
        document.getElementById("sourcePreview").src = currentPreviewUrl;
        document.getElementById("liveLog").textContent =
          (payload.log_messages || []).join("\\n");
        document.getElementById("visionJson").textContent =
          JSON.stringify(payload.vision_json, null, 2);
        document.getElementById("visionSummary").textContent = payload.vision_summary || "";
        document.getElementById("queryPlan").textContent =
          JSON.stringify(payload.query_plan, null, 2);
        document.getElementById("searchHits").textContent =
          JSON.stringify(payload.search_hits, null, 2);
        document.getElementById("datasheetJson").textContent =
          JSON.stringify(payload.datasheet_json, null, 2);
        document.getElementById("renderedDatasheet").textContent =
          payload.rendered_datasheet || "";
        document.getElementById("failures").textContent =
          JSON.stringify(payload.failures || [], null, 2);
      }

      async function parseJsonResponse(response) {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Request failed");
        }
        return payload;
      }

      async function runUpload() {
        const fileInput = document.getElementById("fileInput");
        if (!fileInput.files.length) return;
        const form = new FormData();
        form.append("image", fileInput.files[0]);
        document.getElementById("liveLog").textContent = "submitting upload...";
        try {
          const response = await fetch("/api/diagnose/upload", { method: "POST", body: form });
          renderResult(await parseJsonResponse(response));
        } catch (error) {
          document.getElementById("liveLog").textContent = String(error);
        }
      }

      async function runUrl() {
        const imageUrl = document.getElementById("urlInput").value.trim();
        if (!imageUrl) return;
        document.getElementById("liveLog").textContent = "fetching remote image...";
        try {
          const response = await fetch("/api/diagnose/url", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image_url: imageUrl }),
          });
          renderResult(await parseJsonResponse(response));
        } catch (error) {
          document.getElementById("liveLog").textContent = String(error);
        }
      }

      async function exportCase() {
        if (!currentExportToken) return;
        try {
          const response = await fetch("/api/export", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              export_token: currentExportToken,
              analyst_note: document.getElementById("analystNote").value,
            }),
          });
          document.getElementById("exportResult").textContent = JSON.stringify(
            await parseJsonResponse(response),
            null,
            2
          );
        } catch (error) {
          document.getElementById("exportResult").textContent = String(error);
        }
      }

      document.getElementById("uploadButton").addEventListener("click", runUpload);
      document.getElementById("urlButton").addEventListener("click", runUrl);
      document.getElementById("exportButton").addEventListener("click", exportCase);
    </script>
  </body>
</html>
"""


def create_diagnostic_app(
    *,
    work_root: Path | None = None,
    export_root: Path | None = None,
    vision_backend: VisionBackend | None = None,
    search_provider: SearchProvider | None = None,
    synthesis_backend: SynthesisBackend | None = None,
    fetch_image_bytes: Callable[[str], bytes] | None = None,
) -> FastAPI:
    """Create the local diagnostic web app."""
    app = FastAPI(title="Fast Foto Forensics Diagnostic")
    app.state.work_root = work_root or Path(".tmp") / "web-diagnostic"
    app.state.export_root = export_root or Path("artifacts") / "diagnostic_exports"
    app.state.vision_backend = vision_backend or OllamaVisionBackend()
    app.state.search_provider = search_provider or DDGSSearchProvider()
    app.state.synthesis_backend = synthesis_backend or OllamaDatasheetSynthesisBackend()
    app.state.fetch_image_bytes = fetch_image_bytes or _fetch_remote_image_bytes
    app.state.export_cache = {}

    @app.get("/", response_class=HTMLResponse)
    def root() -> str:
        return _PAGE_HTML

    @app.post("/api/diagnose/upload")
    def diagnose_upload(image: Annotated[UploadFile, File(...)]) -> dict[str, Any]:
        image_bytes = image.file.read()
        request = DiagnosticRequest.from_upload_bytes(image.filename or "upload-image", image_bytes)
        try:
            result = run_diagnostic_request(
                request,
                work_root=app.state.work_root / uuid4().hex,
                vision_backend=app.state.vision_backend,
                search_provider=app.state.search_provider,
                synthesis_backend=app.state.synthesis_backend,
                fetch_image_bytes=app.state.fetch_image_bytes,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        token = uuid4().hex
        export_cache = cast(dict[str, CachedDiagnosticCase], app.state.export_cache)
        export_cache[token] = CachedDiagnosticCase(request=request, result=result)
        payload = result.to_dict()
        payload["export_token"] = token
        return payload

    @app.post("/api/diagnose/url")
    def diagnose_url(request_body: UrlDiagnosticRequest) -> dict[str, Any]:
        request = DiagnosticRequest.from_image_url(request_body.image_url)
        try:
            result = run_diagnostic_request(
                request,
                work_root=app.state.work_root / uuid4().hex,
                vision_backend=app.state.vision_backend,
                search_provider=app.state.search_provider,
                synthesis_backend=app.state.synthesis_backend,
                fetch_image_bytes=app.state.fetch_image_bytes,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        token = uuid4().hex
        export_cache = cast(dict[str, CachedDiagnosticCase], app.state.export_cache)
        export_cache[token] = CachedDiagnosticCase(request=request, result=result)
        payload = result.to_dict()
        payload["export_token"] = token
        return payload

    @app.post("/api/export")
    def export_case(request_body: ExportRequest) -> dict[str, str]:
        export_cache = cast(dict[str, CachedDiagnosticCase], app.state.export_cache)
        cached = export_cache.get(request_body.export_token)
        if cached is None:
            raise HTTPException(status_code=404, detail="Unknown export token")
        exported = export_diagnostic_fixture(
            cached.request,
            cached.result,
            export_root=app.state.export_root,
            analyst_note=request_body.analyst_note,
        )
        return {
            "image_path": str(exported.image_path),
            "metadata_path": str(exported.metadata_path),
        }

    return app
