"""Automated verification tests for PlaceFlow AI 3-portal RBAC, ERP, HR credibility & tests."""

import copy
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server
from erp_db import verify_against_erp
from router_engine import DEFAULT_JDS, _build_ssl_context, evaluate_deterministic_rules


def test_erp_and_deterministic_router() -> None:
    ctx = _build_ssl_context()
    assert ctx.cert_store_stats()["x509_ca"] > 0

    # ERP exact verification vs tampering detection
    ok_erp = verify_against_erp("kiran.gowda@rit.edu", 7.25, "ECE", 0, claimed_semester=7)
    assert ok_erp["status"] == "VERIFIED" and ok_erp["usn"] == "1MS23EC055"

    bad_erp = verify_against_erp("kiran.gowda@rit.edu", 9.10, "CSE", 0, claimed_semester=8)
    assert bad_erp["status"] == "MISMATCH_FLAGGED" and len(bad_erp["discrepancies"]) == 3

    cloud_jd = DEFAULT_JDS[0]

    # 1. Strong match -> SHORTLISTED + high credibility
    res1 = evaluate_deterministic_rules(
        {
            "email": "aarav.sharma@rit.edu",
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
    assert res1["route"] == "SHORTLISTED" and res1["matchPct"] == 100
    assert res1["credibility"]["score"] >= 90

    # 2. Buzzword / Skill-Gap -> UPSKILL_TRACK + YouTube courses
    res2 = evaluate_deterministic_rules(
        {
            "email": "rohan.verma@rit.edu",
            "branch": "CSE",
            "cgpa": 7.9,
            "active_backlogs": 0,
            "verified_skills": [
                {"skill": "Python", "evidence_source": "CLI"},
                {"skill": "Git", "evidence_source": "Repo"},
            ],
            "unverified_claims": [{"skill": "Kubernetes", "reason": "No proof"}],
            "upskilling_plan_7_days": [
                {"day": "Day 1-2", "focus_topic": "FastAPI", "mini_task": "API", "youtube_query": "FastAPI"}
            ],
        },
        cloud_jd,
        DEFAULT_JDS,
    )
    assert res2["route"] == "UPSKILL_TRACK" and res2["routeLabel"] == "Flagged + Upskill"
    assert any(c["skill"] == "Docker" for c in res2["recommendedCourses"])

    # 3. ECE/Low CGPA -> REROUTED to DataPulse
    res3 = evaluate_deterministic_rules(
        {
            "email": "meera.nair@rit.edu",
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
    assert res3["route"] == "REROUTED" and res3["altMatches"][0]["jdId"] == "data"

    # 4. Cutoff miss WITH strong verified projects -> PORTFOLIO_EXCEPTION
    # Even if resume lied and wrote cgpa 9.0, ERP forces 7.25 -> still caught!
    res4 = evaluate_deterministic_rules(
        {
            "email": "kiran.gowda@rit.edu",
            "branch": "ECE",
            "cgpa": 9.0,
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
    assert res4["route"] == "PORTFOLIO_EXCEPTION"
    assert res4["erpVerification"]["status"] == "MISMATCH_FLAGGED"


def _invoke(method: str, path: str, body: dict | None = None, token: str = "") -> tuple[int, bytes]:
    raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
    headers = {"Content-Length": str(len(raw_body))}
    if token:
        headers["X-Session-Token"] = token

    class DummyHandler(server.PlaceFlowHandler):
        def __init__(self) -> None:
            self.path = path
            self.headers = headers
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


def test_3_portal_rbac_and_proctored_test() -> None:
    server.SESSIONS.clear()
    server.RESULTS_STORE.clear()
    server.TESTS_STORE.clear()
    server.JDS_STORE[:] = copy.deepcopy(DEFAULT_JDS)
    server.ACTIVE_JD_SNAPSHOT = server.JDS_STORE[0]

    assert _invoke("GET", "/")[0] == 200
    assert _invoke("GET", "/api/demo-resumes")[0] == 401
    assert _invoke("GET", "/api/hr/candidates")[0] == 401
    assert _invoke("GET", "/api/student/me")[0] == 401

    college_tok = json.loads(
        _invoke("POST", "/api/login", {"role": "college", "email": server.COLLEGE_EMAIL, "passcode": server.COLLEGE_PASSCODE})[1].decode("utf-8")
    )["token"]
    hr_tok = json.loads(
        _invoke("POST", "/api/login", {"role": "hr", "email": "hr@cloudbackend.com", "passcode": server.HR_PASSCODE})[1].decode("utf-8")
    )["token"]
    ananya_tok = json.loads(
        _invoke("POST", "/api/login", {"role": "student", "email": "ananya.rao@rit.edu", "passcode": server.STUDENT_PASSCODE})[1].decode("utf-8")
    )["token"]

    # Strict cross-portal 403 isolation
    assert _invoke("GET", "/api/hr/candidates", token=college_tok)[0] == 403
    assert _invoke("GET", "/api/student/me", token=college_tok)[0] == 403
    assert _invoke("GET", "/api/college/analytics", token=hr_tok)[0] == 403
    assert _invoke("GET", "/api/student/me", token=hr_tok)[0] == 403
    assert _invoke("GET", "/api/college/analytics", token=ananya_tok)[0] == 403
    assert _invoke("GET", "/api/hr/candidates", token=ananya_tok)[0] == 403

    # College can verify ERP & fetch 5 sample PDFs
    assert len(json.loads(_invoke("GET", "/api/demo-resumes", token=college_tok)[1].decode("utf-8"))["files"]) == 5
    erp_res = json.loads(
        _invoke("POST", "/api/college/erp-verify", {"email": "ananya.rao@rit.edu", "resumeCgpa": 8.2, "resumeBranch": "ISE", "resumeBacklogs": 0, "claimedSemester": 7}, token=college_tok)[1].decode("utf-8")
    )
    assert erp_res["erpVerification"]["verified"] is True

    # Seed Ananya as UPSKILL_TRACK (missing REST APIs, Docker) and Aarav as SHORTLISTED
    ananya_ext = {
        "student_name": "Ananya Rao",
        "email": "ananya.rao@rit.edu",
        "branch": "ISE",
        "cgpa": 8.2,
        "active_backlogs": 0,
        "verified_skills": [
            {"skill": "Python", "evidence_source": "MessMenu"},
            {"skill": "SQL", "evidence_source": "MessMenu"},
            {"skill": "Git", "evidence_source": "MessMenu"},
        ],
        "unverified_claims": [],
        "project_summary": "Python & SQL CLI tools.",
        "upskilling_plan_7_days": [],
        "drafted_notification": "Upskill required.",
    }
    aarav_ext = {
        "student_name": "Aarav Sharma",
        "email": "aarav.sharma@rit.edu",
        "branch": "CSE",
        "cgpa": 8.72,
        "active_backlogs": 0,
        "verified_skills": [
            {"skill": "Python", "evidence_source": "CampusRide"},
            {"skill": "SQL", "evidence_source": "CampusRide"},
            {"skill": "REST APIs", "evidence_source": "CampusRide"},
            {"skill": "Docker", "evidence_source": "CampusRide"},
            {"skill": "Git", "evidence_source": "CampusRide"},
        ],
        "unverified_claims": [],
        "project_summary": "Full FastAPI + Docker suite.",
        "upskilling_plan_7_days": [],
        "drafted_notification": "Shortlisted.",
    }
    server.RESULTS_STORE.extend(
        [
            {"id": "rec_ananya", "fileName": "ananya.pdf", "status": "ok", "extracted": ananya_ext, "routing": evaluate_deterministic_rules(ananya_ext, DEFAULT_JDS[0], DEFAULT_JDS), "checkedDays": {}, "appliedAlt": False, "skillTest": None},
            {"id": "rec_aarav", "fileName": "aarav.pdf", "status": "ok", "extracted": aarav_ext, "routing": evaluate_deterministic_rules(aarav_ext, DEFAULT_JDS[0], DEFAULT_JDS), "checkedDays": {}, "appliedAlt": False, "skillTest": None},
        ]
    )

    # College Analytics checks branch acceptance rates & lacking skills
    analytics = json.loads(_invoke("GET", "/api/college/analytics", token=college_tok)[1].decode("utf-8"))
    cse_stat = next(b for b in analytics["branchStats"] if b["branch"] == "CSE")
    assert cse_stat["acceptanceRatePct"] == 100
    assert any(s["skill"] == "Docker" for s in analytics["topLackingSkills"])

    # HR sees only Aarav initially (with credibility score)
    hr_before = json.loads(_invoke("GET", "/api/hr/candidates", token=hr_tok)[1].decode("utf-8"))
    assert len(hr_before["candidates"]) == 1 and hr_before["candidates"][0]["id"] == "rec_aarav"

    # Ananya generates AI skill test (ensure no answer key leaked!) and passes with webcam/mic
    orig_load = server.load_api_key
    server.load_api_key = lambda: ""  # test deterministic local question bank cleanly
    try:
        st_gen, gen_b = _invoke("POST", "/api/student/generate-test", {"jdId": "cloud", "skills": ["Docker", "REST APIs"]}, token=ananya_tok)
        assert st_gen == 200
        gen = json.loads(gen_b.decode("utf-8"))
        assert len(gen["questions"]) == 5
        assert all("correctIndex" not in q for q in gen["questions"])
    finally:
        server.load_api_key = orig_load

    correct_answers = [q["correctIndex"] for q in server.TESTS_STORE[gen["testId"]]["questions"]]
    st_sub, sub_b = _invoke(
        "POST",
        "/api/student/submit-test",
        {"testId": gen["testId"], "answers": correct_answers, "proctoring": {"webcamActive": True, "micActive": True, "tabSwitches": 0, "durationSec": 45}},
        token=ananya_tok,
    )
    assert st_sub == 200
    sub = json.loads(sub_b.decode("utf-8"))
    assert sub["result"]["passed"] is True
    assert sub["updatedRecord"]["routing"]["route"] == "SHORTLISTED"

    # Now HR sees BOTH Aarav and Ananya!
    hr_after = json.loads(_invoke("GET", "/api/hr/candidates", token=hr_tok)[1].decode("utf-8"))
    assert len(hr_after["candidates"]) == 2


if __name__ == "__main__":
    test_erp_and_deterministic_router()
    test_3_portal_rbac_and_proctored_test()
    print("ALL TESTS PASSED")
