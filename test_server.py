"""Automated verification tests for PlaceFlow AI rule engine and HTTP handlers."""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server
from router_engine import DEFAULT_JDS, _build_ssl_context, evaluate_deterministic_rules


def test_deterministic_router() -> None:
    ctx = _build_ssl_context()
    assert ctx.cert_store_stats()["x509_ca"] > 0, "Expected loaded CA certificates"
    cloud_jd = DEFAULT_JDS[0]

    # 1. Strong match -> SHORTLISTED
    res1 = evaluate_deterministic_rules(
        {
            "branch": "Computer Science & Engineering (CSE)",
            "cgpa": 8.72,
            "active_backlogs": 0,
            "verified_skills": [
                {"skill": "Python", "evidence_source": "CampusRide"},
                {"skill": "FastAPI", "evidence_source": "CampusRide"},
                {"skill": "PostgreSQL", "evidence_source": "CampusRide"},
                {"skill": "Docker", "evidence_source": "CampusRide"},
                {"skill": "Git", "evidence_source": "CampusRide"},
            ],
            "unverified_claims": [],
        },
        cloud_jd,
        DEFAULT_JDS,
    )
    assert res1["route"] == "SHORTLISTED", res1
    assert res1["matchPct"] == 100, res1

    # 2. Buzzword student -> UPSKILL_TRACK (Flagged)
    res2 = evaluate_deterministic_rules(
        {
            "branch": "CSE",
            "cgpa": 7.9,
            "active_backlogs": 0,
            "verified_skills": [
                {"skill": "Python", "evidence_source": "CLI"},
                {"skill": "Git", "evidence_source": "Repo"},
            ],
            "unverified_claims": [
                {"skill": "Kubernetes", "reason": "No project proof"},
            ],
        },
        cloud_jd,
        DEFAULT_JDS,
    )
    assert res2["route"] == "UPSKILL_TRACK", res2
    assert res2["routeLabel"] == "Flagged + Upskill", res2

    # 3. Low CGPA / ECE -> REROUTED to DataPulse Analytics
    res3 = evaluate_deterministic_rules(
        {
            "branch": "ECE",
            "cgpa": 7.12,
            "active_backlogs": 0,
            "verified_skills": [
                {"skill": "Python", "evidence_source": "Pandas"},
                {"skill": "SQL", "evidence_source": "Retail"},
                {"skill": "Excel", "evidence_source": "Retail"},
                {"skill": "Power BI", "evidence_source": "Retail"},
            ],
            "unverified_claims": [],
        },
        cloud_jd,
        DEFAULT_JDS,
    )
    assert res3["route"] == "REROUTED", res3
    assert res3["altMatches"][0]["jdId"] == "data", res3

    # 4. Cutoff miss WITH strong verified projects -> PORTFOLIO_EXCEPTION
    res4 = evaluate_deterministic_rules(
        {
            "branch": "ECE",
            "cgpa": 7.25,
            "active_backlogs": 0,
            "verified_skills": [
                {"skill": "Python", "evidence_source": "CampusPay"},
                {"skill": "FastAPI", "evidence_source": "CampusPay"},
                {"skill": "PostgreSQL", "evidence_source": "CampusPay"},
                {"skill": "Docker", "evidence_source": "CampusPay"},
                {"skill": "Git", "evidence_source": "CampusPay"},
            ],
            "unverified_claims": [],
        },
        cloud_jd,
        DEFAULT_JDS,
    )
    assert res4["route"] == "PORTFOLIO_EXCEPTION", res4
    assert res4["routeLabel"] == "Portfolio Exception", res4

    # 5. Backlogs violation with weak/no verified skills -> Blocked
    res5 = evaluate_deterministic_rules(
        {
            "branch": "CSE",
            "cgpa": 8.0,
            "active_backlogs": 2,
            "verified_skills": [],
            "unverified_claims": [],
        },
        cloud_jd,
        DEFAULT_JDS,
    )
    assert res5["route"] == "REROUTED", res5
    assert res5["altMatches"] == [], res5


def _invoke_handler(method: str, path: str, body: dict | None = None) -> tuple[int, bytes]:
    raw_body = json.dumps(body).encode("utf-8") if body is not None else b""

    class DummyHandler(server.PlaceFlowHandler):
        def __init__(self) -> None:
            self.path = path
            self.headers = {"Content-Length": str(len(raw_body))}
            self.rfile = io.BytesIO(raw_body)
            self.wfile = io.BytesIO()
            self.status_code = 0

        def send_response(self, code: int, message: str | None = None) -> None:
            self.status_code = code

        def send_header(self, keyword: str, value: str) -> None:
            return

        def end_headers(self) -> None:
            return

    h = DummyHandler()
    if method == "GET":
        h.do_GET()
    else:
        h.do_POST()
    return h.status_code, h.wfile.getvalue()


def test_http_handlers() -> None:
    status, html_bytes = _invoke_handler("GET", "/")
    html = html_bytes.decode("utf-8")
    assert status == 200
    assert "PlaceFlow AI" in html
    assert "webhook" not in html.lower()

    status, health_bytes = _invoke_handler("GET", "/api/health")
    health = json.loads(health_bytes.decode("utf-8"))
    assert status == 200 and health["ok"] is True

    status, jds_bytes = _invoke_handler("GET", "/api/jds")
    jds = json.loads(jds_bytes.decode("utf-8"))
    assert status == 200 and len(jds["jds"]) == 3

    status, demos_bytes = _invoke_handler("GET", "/api/demo-resumes")
    demos = json.loads(demos_bytes.decode("utf-8"))
    assert status == 200 and len(demos["files"]) == 5
    assert all(f["fileName"].endswith(".pdf") and len(f["pdfBase64"]) > 1000 for f in demos["files"])

    orig_load = server.load_api_key
    server.load_api_key = lambda: ""
    try:
        status, err_bytes = _invoke_handler("POST", "/api/verify-resume", {"fileName": "test.pdf"})
        assert status == 400
        err_json = json.loads(err_bytes.decode("utf-8"))
        assert "Gemini API key" in err_json["error"]
    finally:
        server.load_api_key = orig_load


if __name__ == "__main__":
    test_deterministic_router()
    test_http_handlers()
    print("ALL TESTS PASSED")
