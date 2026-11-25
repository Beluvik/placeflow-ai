"""Local zero-dependency HTTP server with Role-Based Access Control for PlaceFlow AI."""

import base64
import json
import os
import secrets
import threading
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

ADMIN_EMAIL = os.environ.get("PLACEFLOW_ADMIN_EMAIL", "admin@rit.edu").lower()
ADMIN_PASSCODE = os.environ.get("PLACEFLOW_ADMIN_PASSCODE", "RIT-ADMIN-2026")
STUDENT_PASSCODE = os.environ.get("PLACEFLOW_STUDENT_PASSCODE", "RIT-STUDENT-2026")

_LOCK = threading.Lock()
SESSIONS: dict[str, dict[str, str]] = {}
RESULTS_STORE: list[dict[str, Any]] = []
ACTIVE_JD_SNAPSHOT: dict[str, Any] = DEFAULT_JDS[0]


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
    """Serves PlaceFlow AI with strict Admin vs Student role isolation."""

    server_version = "PlaceFlowAI/2.0"

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

    def _get_session(self) -> dict[str, str] | None:
        token = self.headers.get("X-Session-Token", "").strip()
        if not token:
            auth = self.headers.get("Authorization", "").strip()
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip()
        if not token:
            return None
        with _LOCK:
            return SESSIONS.get(token)

    def _require_role(self, required_role: str) -> dict[str, str] | None:
        session = self._get_session()
        if not session:
            self._send_json(401, {"error": "Authentication required. Please sign in."})
            return None
        if session["role"] != required_role:
            self._send_json(
                403,
                {
                    "error": (
                        f"Access denied: this endpoint is restricted to {required_role} accounts "
                        f"(signed in as {session['role']})."
                    )
                },
            )
            return None
        return session

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
            session = self._get_session()
            self._send_json(
                200,
                {
                    "ok": True,
                    "hasApiKey": bool(key),
                    "maskedKey": mask_key(key),
                    "models": GEMINI_MODELS,
                    "user": session,
                },
            )
            return

        if path == "/api/me":
            session = self._get_session()
            if not session:
                self._send_json(401, {"error": "Not signed in."})
                return
            self._send_json(200, {"ok": True, "user": session})
            return

        if path == "/api/jds":
            self._send_json(200, {"jds": DEFAULT_JDS})
            return

        if path == "/api/demo-resumes":
            if not self._require_role("admin"):
                return
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

        if path == "/api/admin/results":
            if not self._require_role("admin"):
                return
            with _LOCK:
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "results": list(RESULTS_STORE),
                        "activeJd": ACTIVE_JD_SNAPSHOT,
                    },
                )
            return

        if path == "/api/student/me":
            session = self._require_role("student")
            if not session:
                return
            student_email = session["email"].lower()
            with _LOCK:
                own_records = [
                    r
                    for r in RESULTS_STORE
                    if r.get("status") == "ok"
                    and str(r.get("extracted", {}).get("email", "")).strip().lower()
                    == student_email
                ]
                jd_info = dict(ACTIVE_JD_SNAPSHOT)
            self._send_json(
                200,
                {
                    "ok": True,
                    "student": session,
                    "records": own_records,
                    "activeJd": jd_info,
                },
            )
            return

        self._send_json(404, {"error": f"Unknown route: {path}"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == "/api/login":
            try:
                body = self._read_json()
                role = str(body.get("role", "")).strip().lower()
                email = str(body.get("email", "")).strip().lower()
                passcode = str(body.get("passcode", "")).strip()

                if role == "admin":
                    if email != ADMIN_EMAIL or passcode != ADMIN_PASSCODE:
                        self._send_json(401, {"error": "Invalid Admin email or passcode."})
                        return
                    user = {"role": "admin", "email": email, "name": "Placement Coordinator"}
                elif role == "student":
                    if not email or "@" not in email or passcode != STUDENT_PASSCODE:
                        self._send_json(401, {"error": "Invalid Student email or passcode."})
                        return
                    local = email.split("@", 1)[0].replace(".", " ").title()
                    user = {"role": "student", "email": email, "name": local}
                else:
                    self._send_json(400, {"error": "Role must be 'admin' or 'student'."})
                    return

                token = secrets.token_urlsafe(24)
                with _LOCK:
                    SESSIONS[token] = user
                self._send_json(200, {"ok": True, "token": token, "user": user})
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return

        if path == "/api/logout":
            token = self.headers.get("X-Session-Token", "").strip()
            with _LOCK:
                SESSIONS.pop(token, None)
            self._send_json(200, {"ok": True})
            return

        if path == "/api/config":
            if not self._require_role("admin"):
                return
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

        if path == "/api/admin/clear":
            if not self._require_role("admin"):
                return
            with _LOCK:
                RESULTS_STORE.clear()
            self._send_json(200, {"ok": True})
            return

        if path == "/api/admin/approve-waiver":
            if not self._require_role("admin"):
                return
            try:
                body = self._read_json()
                rec_id = str(body.get("id", ""))
                with _LOCK:
                    target = next((r for r in RESULTS_STORE if r.get("id") == rec_id), None)
                    if not target or target.get("status") != "ok":
                        self._send_json(404, {"error": "Candidate record not found."})
                        return
                    rt = target["routing"]
                    rt["route"] = "SHORTLISTED"
                    rt["routeLabel"] = "Shortlisted (Waiver)"
                    rt["waiverApproved"] = True
                    rt["verdictReason"] = (
                        f"Coordinator approved Portfolio Exception waiver ({rt['matchPct']}% verified project fit) "
                        f"— promoted to HR Shortlist."
                    )
                    updated = dict(target)
                self._send_json(200, {"ok": True, "record": updated})
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return

        if path == "/api/verify-resume":
            if not self._require_role("admin"):
                return
            started = time.time()
            try:
                body = self._read_json()
                api_key = load_api_key()
                if not api_key:
                    self._send_json(
                        400,
                        {
                            "error": "No Gemini API key configured. Click 'Set Gemini Key' in the top bar first."
                        },
                    )
                    return

                jd = body.get("jd") or DEFAULT_JDS[0]
                all_jds = body.get("allJds") or DEFAULT_JDS
                pdf_b64 = body.get("pdfBase64")
                resume_text = body.get("resumeText")
                rec_id = str(body.get("id") or f"rec_{secrets.token_hex(6)}")
                file_name = str(body.get("fileName", "resume.pdf"))

                audit = call_gemini_audit(
                    api_key=api_key,
                    jd=jd,
                    pdf_base64=pdf_b64,
                    resume_text=resume_text,
                )
                routing = evaluate_deterministic_rules(audit["extracted"], jd, all_jds)
                elapsed_ms = round((time.time() - started) * 1000)

                record = {
                    "id": rec_id,
                    "fileName": file_name,
                    "status": "ok",
                    "extracted": audit["extracted"],
                    "routing": routing,
                    "meta": {
                        "modelUsed": audit["modelUsed"],
                        "attemptsLog": audit["attemptsLog"],
                        "durationMs": elapsed_ms,
                    },
                    "checkedDays": {},
                    "appliedAlt": False,
                }
                with _LOCK:
                    global ACTIVE_JD_SNAPSHOT
                    ACTIVE_JD_SNAPSHOT = jd
                    RESULTS_STORE[:] = [r for r in RESULTS_STORE if r.get("id") != rec_id]
                    RESULTS_STORE.append(record)

                self._send_json(200, {"ok": True, **record})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        if path == "/api/student/toggle-day":
            session = self._require_role("student")
            if not session:
                return
            try:
                body = self._read_json()
                rec_id = str(body.get("id", ""))
                day_idx = str(body.get("dayIdx", ""))
                student_email = session["email"].lower()
                with _LOCK:
                    target = next((r for r in RESULTS_STORE if r.get("id") == rec_id), None)
                    if not target:
                        self._send_json(404, {"error": "Record not found."})
                        return
                    owner_email = str(target.get("extracted", {}).get("email", "")).strip().lower()
                    if owner_email != student_email:
                        self._send_json(403, {"error": "Cannot modify another student's checklist."})
                        return
                    checked = target.setdefault("checkedDays", {})
                    checked[day_idx] = not bool(checked.get(day_idx, False))
                self._send_json(200, {"ok": True, "checkedDays": checked})
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return

        if path == "/api/student/confirm-reroute":
            session = self._require_role("student")
            if not session:
                return
            try:
                body = self._read_json()
                rec_id = str(body.get("id", ""))
                student_email = session["email"].lower()
                with _LOCK:
                    target = next((r for r in RESULTS_STORE if r.get("id") == rec_id), None)
                    if not target:
                        self._send_json(404, {"error": "Record not found."})
                        return
                    owner_email = str(target.get("extracted", {}).get("email", "")).strip().lower()
                    if owner_email != student_email:
                        self._send_json(403, {"error": "Cannot modify another student's drive."})
                        return
                    target["appliedAlt"] = True
                self._send_json(200, {"ok": True})
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return

        self._send_json(404, {"error": f"Unknown route: {path}"})


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), PlaceFlowHandler)
    print(f"PlaceFlow AI running at http://{HOST}:{PORT}")
    print(f"Admin login:   {ADMIN_EMAIL} / {ADMIN_PASSCODE}")
    print(f"Student login: <student>@rit.edu / {STUDENT_PASSCODE}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()


if __name__ == "__main__":
    main()
