"""Gemini API verification client and deterministic placement auto-router."""

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any


def _build_ssl_context() -> ssl.SSLContext:
    """Use certifi or macOS system CA bundle so python.org macOS builds verify TLS cleanly."""
    try:
        import certifi  # type: ignore

        ca_path = certifi.where()
        if ca_path and os.path.exists(ca_path):
            return ssl.create_default_context(cafile=ca_path)
    except ImportError:
        pass
    if os.path.exists("/etc/ssl/cert.pem"):
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


_SSL_CONTEXT = _build_ssl_context()

GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
]

DEFAULT_JDS = [
    {
        "id": "cloud",
        "company": "CloudBackend Systems",
        "role": "Software Engineer (FTE)",
        "ctc": "12 LPA",
        "minCgpa": 7.5,
        "allowedBranches": ["CSE", "ISE", "AIML"],
        "maxBacklogs": 0,
        "mustHaveSkills": ["Python", "SQL", "REST APIs", "Docker", "Git"],
        "goodToHaveSkills": ["AWS", "Redis"],
    },
    {
        "id": "frontend",
        "company": "PixelCraft Labs",
        "role": "Frontend Developer Intern",
        "ctc": "45k/mo + PPO",
        "minCgpa": 7.0,
        "allowedBranches": ["CSE", "ISE", "ECE", "AIML"],
        "maxBacklogs": 0,
        "mustHaveSkills": ["React", "TypeScript", "HTML/CSS", "Git"],
        "goodToHaveSkills": ["Next.js", "Tailwind CSS"],
    },
    {
        "id": "data",
        "company": "DataPulse Analytics",
        "role": "Junior Data Analyst",
        "ctc": "9.5 LPA",
        "minCgpa": 6.8,
        "allowedBranches": ["CSE", "ISE", "ECE", "EEE", "MECH"],
        "maxBacklogs": 1,
        "mustHaveSkills": ["Python", "SQL", "Excel", "Data Visualization"],
        "goodToHaveSkills": ["Power BI", "Statistics"],
    },
]

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "student_name": {"type": "STRING"},
        "email": {"type": "STRING"},
        "branch": {"type": "STRING"},
        "cgpa": {"type": "NUMBER"},
        "active_backlogs": {"type": "INTEGER"},
        "graduation_year": {"type": "INTEGER"},
        "verified_skills": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "skill": {"type": "STRING"},
                    "evidence_source": {"type": "STRING"},
                },
                "required": ["skill", "evidence_source"],
            },
        },
        "unverified_claims": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "skill": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
                "required": ["skill", "reason"],
            },
        },
        "project_summary": {"type": "STRING"},
        "missing_must_have_skills": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
        "upskilling_plan_7_days": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "day": {"type": "STRING"},
                    "focus_topic": {"type": "STRING"},
                    "mini_task": {"type": "STRING"},
                },
                "required": ["day", "focus_topic", "mini_task"],
            },
        },
        "drafted_notification": {"type": "STRING"},
    },
    "required": [
        "student_name",
        "email",
        "branch",
        "cgpa",
        "active_backlogs",
        "verified_skills",
        "unverified_claims",
        "project_summary",
        "missing_must_have_skills",
        "upskilling_plan_7_days",
        "drafted_notification",
    ],
}


def _normalize_branch(branch: str) -> str:
    """Normalize common campus engineering branch names into short codes."""
    raw = (branch or "").strip().upper()
    mapping = {
        "COMPUTER SCIENCE": "CSE",
        "COMPUTER SCIENCE AND ENGINEERING": "CSE",
        "INFORMATION SCIENCE": "ISE",
        "INFORMATION SCIENCE AND ENGINEERING": "ISE",
        "ELECTRONICS AND COMMUNICATION": "ECE",
        "ELECTRICAL AND ELECTRONICS": "EEE",
        "ARTIFICIAL INTELLIGENCE": "AIML",
        "AI & ML": "AIML",
        "MECHANICAL": "MECH",
    }
    for key, code in mapping.items():
        if key in raw:
            return code
    for code in ("CSE", "ISE", "AIML", "ECE", "EEE", "MECH"):
        if code in raw:
            return code
    return raw or "UNKNOWN"


def _skill_matches(candidate_skills: list[str], target_skill: str) -> bool:
    """Case-insensitive substring/synonym match for verified technical skills."""
    t = target_skill.strip().lower()
    synonyms = {
        "rest apis": ("rest api", "fastapi", "express", "flask api", "endpoints"),
        "sql": ("sql", "postgresql", "mysql", "sqlite"),
        "data visualization": ("data visualization", "power bi", "tableau", "matplotlib"),
        "html/css": ("html", "css", "tailwind"),
    }
    aliases = synonyms.get(t, (t,))
    for s in candidate_skills:
        sl = s.strip().lower()
        if t == sl or t in sl or sl in t or any(a in sl for a in aliases):
            return True
    return False


def evaluate_deterministic_rules(
    extracted: dict[str, Any], target_jd: dict[str, Any], all_jds: list[dict[str, Any]]
) -> dict[str, Any]:
    """Run strict non-AI eligibility rules and 3-track auto-routing."""
    cgpa = float(extracted.get("cgpa") or 0.0)
    branch = _normalize_branch(str(extracted.get("branch") or ""))
    backlogs = int(extracted.get("active_backlogs") or 0)

    min_cgpa = float(target_jd.get("minCgpa") or 0.0)
    allowed_branches = [b.strip().upper() for b in target_jd.get("allowedBranches", [])]
    max_backlogs = int(target_jd.get("maxBacklogs") or 0)

    passes_cgpa = cgpa >= min_cgpa
    passes_branch = branch in allowed_branches
    passes_backlogs = backlogs <= max_backlogs

    verified_names = [
        str(v.get("skill", "")).strip()
        for v in extracted.get("verified_skills", [])
        if v.get("skill")
    ]
    unverified_claims = extracted.get("unverified_claims", [])

    must_have = target_jd.get("mustHaveSkills", [])
    missing_must_have = [
        s for s in must_have if not _skill_matches(verified_names, s)
    ]
    # Merge any extra gaps Gemini explicitly caught while keeping deterministic set clean
    total_req = max(len(must_have), 1)
    match_pct = round(((total_req - len(missing_must_have)) / total_req) * 100)

    alt_matches = []
    if not (passes_cgpa and passes_branch and passes_backlogs):
        for other in all_jds:
            if other.get("id") == target_jd.get("id"):
                continue
            other_branches = [b.strip().upper() for b in other.get("allowedBranches", [])]
            ok = (
                cgpa >= float(other.get("minCgpa") or 0.0)
                and branch in other_branches
                and backlogs <= int(other.get("maxBacklogs") or 0)
            )
            if ok:
                other_must = other.get("mustHaveSkills", [])
                other_missing = [
                    s for s in other_must if not _skill_matches(verified_names, s)
                ]
                other_pct = round(
                    ((max(len(other_must), 1) - len(other_missing)) / max(len(other_must), 1))
                    * 100
                )
                alt_matches.append(
                    {
                        "jdId": other.get("id"),
                        "company": other.get("company"),
                        "role": other.get("role"),
                        "ctc": other.get("ctc", ""),
                        "fitPct": other_pct,
                        "missingSkills": other_missing,
                    }
                )
        alt_matches.sort(key=lambda x: x["fitPct"], reverse=True)

    if not (passes_cgpa and passes_branch and passes_backlogs):
        route = "REROUTED"
        reasons = []
        if not passes_cgpa:
            reasons.append(f"CGPA {cgpa} < {min_cgpa}")
        if not passes_branch:
            reasons.append(f"Branch {branch} not in {', '.join(allowed_branches)}")
        if not passes_backlogs:
            reasons.append(f"Backlogs {backlogs} > max {max_backlogs}")

        if alt_matches:
            route_label = "Auto-Rerouted"
            best = alt_matches[0]
            verdict_reason = (
                f"Ineligible ({'; '.join(reasons)}). Auto-rerouted to "
                f"{best['company']} — {best['role']} ({best['fitPct']}% skill fit)."
            )
        else:
            route_label = "Blocked (Cutoff)"
            verdict_reason = f"Ineligible across active JDs ({'; '.join(reasons)})."
    elif match_pct >= 75 and len(unverified_claims) == 0:
        route = "SHORTLISTED"
        route_label = "Shortlisted"
        verdict_reason = (
            f"Passes all hard rules and {match_pct}% of must-have skills are backed by project proof."
        )
    else:
        route = "UPSKILL_TRACK"
        if len(unverified_claims) > 0:
            route_label = "Flagged + Upskill"
            verdict_reason = (
                f"Meets academic cutoffs, but {len(unverified_claims)} claimed skill(s) lacked project evidence."
            )
        else:
            route_label = "Upskill Track"
            verdict_reason = (
                f"Meets cutoffs, missing {', '.join(missing_must_have)} — assigned 7-day roadmap."
            )

    return {
        "normalizedBranch": branch,
        "passesCgpa": passes_cgpa,
        "passesBranch": passes_branch,
        "passesBacklogs": passes_backlogs,
        "missingMustHave": missing_must_have,
        "matchPct": match_pct,
        "route": route,
        "routeLabel": route_label,
        "verdictReason": verdict_reason,
        "altMatches": alt_matches,
    }


def call_gemini_audit(
    api_key: str,
    jd: dict[str, Any],
    pdf_base64: str | None = None,
    resume_text: str | None = None,
) -> dict[str, Any]:
    """Call Gemini API directly with retry + model fallback and strict JSON schema."""
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY. Set your key in Settings first.")

    instruction = (
        "You are PlaceFlow AI, a strict Campus Placement Cell Resume Verification Auditor.\n"
        "Analyze the student's resume against the target Job Description (JD) below.\n"
        "CRITICAL VERIFICATION RULES:\n"
        "1. Extract exact student_name, email, branch (e.g., CSE, ISE, ECE, AIML, EEE, MECH), cgpa (numeric), active_backlogs (integer, 0 if not listed/none), graduation_year.\n"
        "2. `verified_skills`: ONLY include a skill if there is concrete evidence in a Project, Internship, or Work Experience bullet proving they actually used it. Quote the specific project/internship in `evidence_source`.\n"
        "3. `unverified_claims`: Any technical skill listed in a Skills/Summary section that has ZERO mention or proof inside Projects/Experience MUST go here with a clear `reason`.\n"
        "4. `missing_must_have_skills`: List all JD must-have skills not present in `verified_skills`.\n"
        "5. `upskilling_plan_7_days`: Provide 3 concise actionable steps (e.g. Day 1-2, Day 3-4, Day 5-7) to close missing skills or build proof for unverified skills.\n"
        "6. `drafted_notification`: Write a concise 2-3 sentence placement notification email to the student.\n\n"
        f"TARGET JD:\n{json.dumps(jd, indent=2)}"
    )

    parts: list[dict[str, Any]] = [{"text": instruction}]
    if pdf_base64:
        clean_b64 = pdf_base64.split(",", 1)[-1].strip()
        parts.append({"inlineData": {"mimeType": "application/pdf", "data": clean_b64}})
    elif resume_text:
        parts.append({"text": f"\n\nSTUDENT RESUME TEXT:\n{resume_text}"})
    else:
        raise ValueError("Either pdfBase64 or resumeText must be provided.")

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }
    body_bytes = json.dumps(payload).encode("utf-8")

    attempts_log: list[str] = []
    last_error = "Unknown Gemini error"

    for model in GEMINI_MODELS:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        for attempt in range(2):
            req = urllib.request.Request(
                url,
                data=body_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=45, context=_SSL_CONTEXT) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                text = raw["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
                attempts_log.append(f"{model} succeeded (try {attempt + 1})")
                return {
                    "extracted": parsed,
                    "modelUsed": model,
                    "attemptsLog": attempts_log,
                }
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code} on {model}: {err_body[:300]}"
                attempts_log.append(last_error)
                if exc.code in (429, 500, 503, 504):
                    time.sleep(1.2 * (attempt + 1))
                    continue
                if exc.code == 404:
                    break
                raise RuntimeError(last_error) from exc
            except Exception as exc:
                last_error = f"{model} error: {exc}"
                attempts_log.append(last_error)
                break

    raise RuntimeError(f"All Gemini fallback models failed. Last error: {last_error}")
