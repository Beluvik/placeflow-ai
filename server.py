"""Local zero-dependency HTTP server for PlaceFlow AI (PS-CA4)."""

import base64
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from router_engine import (
    DEFAULT_JDS,
    GEMINI_MODELS,
    call_gemini_audit,
    evaluate_deterministic_rules,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SAMPLE_DIR = BASE_DIR / "sample_resumes"
ENV_PATH = BASE_DIR / ".env"

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))


def load_api_key() -> str:
    """Read GEMINI_API_KEY from environment or local .env file."""
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def save_api_key(key: str) -> None:
    """Persist GEMINI_API_KEY into local .env file and process env."""
    clean = key.strip()
    os.environ["GEMINI_API_KEY"] = clean
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = [
            ln
            for ln in ENV_PATH.read_text(encoding="utf-8").splitlines()
            if not ln.strip().startswith("GEMINI_API_KEY=")
        ]
    lines.append(f"GEMINI_API_KEY={clean}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask_key(key: str) -> str:
    if len(key) <= 10:
        return "***" if key else ""
    return f"{key[:6]}...{key[-4:]}"


class PlaceFlowHandler(BaseHTTPRequestHandler):
    """Serves the PlaceFlow AI frontend and server-side Gemini verification APIs."""

    server_version = "PlaceFlowAI/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 25 * 1024 * 1024:
            raise ValueError("Payload exceeds 25MB limit.")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == "/" or path == "/index.html":
            html_file = STATIC_DIR / "index.html"
            content = html_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/api/health":
            key = load_api_key()
            self._send_json(
                200,
                {
                    "ok": True,
                    "hasApiKey": bool(key),
                    "maskedKey": mask_key(key),
                    "models": GEMINI_MODELS,
                },
            )
            return

        if path == "/api/jds":
            self._send_json(200, {"jds": DEFAULT_JDS})
            return

        if path == "/api/demo-resumes":
            files = []
            for pdf in sorted(SAMPLE_DIR.glob("*.pdf")):
                b64 = base64.b64encode(pdf.read_bytes()).decode("ascii")
                files.append(
                    {
                        "fileName": pdf.name,
                        "sizeBytes": pdf.stat().st_size,
                        "pdfBase64": b64,
                    }
                )
            self._send_json(200, {"files": files})
            return

        self._send_json(404, {"error": f"Unknown route: {path}"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == "/api/config":
            try:
                body = self._read_json()
                key = str(body.get("apiKey", "")).strip()
                if not key:
                    self._send_json(400, {"error": "API key cannot be empty."})
                    return
                save_api_key(key)
                self._send_json(200, {"ok": True, "maskedKey": mask_key(key)})
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return

        if path == "/api/verify-resume":
            started = time.time()
            try:
                body = self._read_json()
                api_key = load_api_key()
                if not api_key:
                    self._send_json(
                        400,
                        {
                            "error": "No Gemini API key configured. Click 'Set Gemini API Key' in the top bar first."
                        },
                    )
                    return

                jd = body.get("jd") or DEFAULT_JDS[0]
                all_jds = body.get("allJds") or DEFAULT_JDS
                pdf_b64 = body.get("pdfBase64")
                resume_text = body.get("resumeText")

                audit = call_gemini_audit(
                    api_key=api_key,
                    jd=jd,
                    pdf_base64=pdf_b64,
                    resume_text=resume_text,
                )
                routing = evaluate_deterministic_rules(audit["extracted"], jd, all_jds)
                elapsed_ms = round((time.time() - started) * 1000)

                self._send_json(
                    200,
                    {
                        "ok": True,
                        "fileName": body.get("fileName", "resume.pdf"),
                        "extracted": audit["extracted"],
                        "routing": routing,
                        "meta": {
                            "modelUsed": audit["modelUsed"],
                            "attemptsLog": audit["attemptsLog"],
                            "durationMs": elapsed_ms,
                        },
                    },
                )
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        self._send_json(404, {"error": f"Unknown route: {path}"})


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), PlaceFlowHandler)
    print(f"PlaceFlow AI running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()


if __name__ == "__main__":
    main()
