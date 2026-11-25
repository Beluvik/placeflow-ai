"""Gemini API verification client and deterministic placement auto-router."""

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from erp_db import compute_credibility_score, verify_against_erp


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
                    "youtube_query": {"type": "STRING"},
                },
                "required": ["day", "focus_topic", "mini_task", "youtube_query"],
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


SKILL_COURSE_CATALOG: dict[str, tuple[str, str]] = {
    "rest apis": ("REST APIs & FastAPI Crash Course (Hands-On)", "FastAPI Python REST API full course project tutorial"),
    "docker": ("Docker & Docker Compose Full Course", "Docker and Docker Compose full course for beginners hands on"),
    "kubernetes": ("Kubernetes Beginners to Deployment Course", "Kubernetes full course for beginners TechWorld with Nana"),
    "python": ("Python Backend & Problem Solving Course", "Python full course for beginners freeCodeCamp"),
    "sql": ("SQL & PostgreSQL Database Design Course", "PostgreSQL SQL full course freeCodeCamp"),
    "git": ("Git & GitHub Team Workflow Tutorial", "Git and GitHub crash course for beginners"),
    "react": ("React Complete Course + Hooks Project", "React full course freeCodeCamp"),
    "typescript": ("TypeScript Full Course for React Developers", "TypeScript full course for beginners"),
    "html/css": ("Modern Responsive HTML & CSS Course", "HTML CSS full course freeCodeCamp"),
    "next.js": ("Next.js App Router Full Course", "Next.js full course tutorial project"),
    "tailwind css": ("Tailwind CSS Complete UI Course", "Tailwind CSS full course tutorial"),
    "aws": ("AWS Cloud Practitioner & EC2/S3 Hands-On", "AWS full course for beginners freeCodeCamp"),
    "microservices": ("Microservices Architecture & APIs Course", "Microservices architecture full course hands on"),
    "excel": ("Excel Pivot Tables, XLOOKUP & Dashboards", "Microsoft Excel data analysis full course freeCodeCamp"),
    "data visualization": ("Data Visualization with Python & Dashboards", "Data visualization full course Python Matplotlib Power BI"),
    "power bi": ("Power BI End-to-End Dashboard Course", "Power BI full course for beginners"),
    "statistics": ("Statistics for Data Science & Analytics", "Statistics for data science full course freeCodeCamp"),
    "redis": ("Redis Caching & Fast Backend Patterns", "Redis crash course tutorial"),
}


def _youtube_search_url(query: str) -> str:
    """Build a reliable YouTube search URL targeted at full courses."""
    encoded = urllib.parse.quote_plus(query.strip())
    return f"https://www.youtube.com/results?search_query={encoded}"


def build_youtube_courses(
    extracted: dict[str, Any], missing_must_have: list[str]
) -> list[dict[str, str]]:
    """Attach YouTube course links to roadmap steps and build per-skill course cards."""
    for step in extracted.get("upskilling_plan_7_days", []) or []:
        raw_q = str(step.get("youtube_query") or "").strip()
        if not raw_q:
            topic = str(step.get("focus_topic") or "software engineering").strip()
            raw_q = f"{topic} full course tutorial"
        step["youtube_query"] = raw_q
        step["youtube_url"] = _youtube_search_url(raw_q)

    candidates: list[tuple[str, str]] = []
    for skill in missing_must_have:
        candidates.append((skill, "Missing JD Skill"))
    for claim in extracted.get("unverified_claims", []) or []:
        skill_name = str(claim.get("skill") or "").strip()
        if skill_name:
            candidates.append((skill_name, "Needs Project Proof"))

    seen: set[str] = set()
    courses: list[dict[str, str]] = []
    for skill, badge in candidates:
        key = skill.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        title, query = SKILL_COURSE_CATALOG.get(
            key,
            (f"{skill} Full Course & Mini-Project", f"{skill} full course project tutorial"),
        )
        courses.append(
            {
                "skill": skill,
                "badge": badge,
                "courseTitle": title,
                "query": query,
                "url": _youtube_search_url(query),
            }
        )
    return courses


def evaluate_deterministic_rules(
    extracted: dict[str, Any],
    target_jd: dict[str, Any],
    all_jds: list[dict[str, Any]],
    skill_test: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run strict non-AI eligibility rules, College ERP verification, and 4-track auto-routing."""
    resume_cgpa = float(extracted.get("cgpa") or 0.0)
    resume_branch = _normalize_branch(str(extracted.get("branch") or ""))
    resume_backlogs = int(extracted.get("active_backlogs") or 0)
    student_email = str(extracted.get("email") or "").strip().lower()

    erp = verify_against_erp(student_email, resume_cgpa, resume_branch, resume_backlogs)
    # Use official College ERP record as authoritative truth if student is registered
    if erp.get("registeredInErp"):
        cgpa = float(erp["officialCgpa"])
        branch = _normalize_branch(str(erp["officialBranch"]))
        backlogs = int(erp["officialBacklogs"])
    else:
        cgpa = resume_cgpa
        branch = resume_branch
        backlogs = resume_backlogs

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
        reasons = []
        if not passes_cgpa:
            reasons.append(f"CGPA {cgpa} < {min_cgpa}")
        if not passes_branch:
            reasons.append(f"Branch {branch} not in {', '.join(allowed_branches)}")
        if not passes_backlogs:
            reasons.append(f"Backlogs {backlogs} > max {max_backlogs}")

        # New 4th track: Strong verified project proof despite academic cutoff miss
        if match_pct >= 75 and len(unverified_claims) == 0 and len(verified_names) >= 3:
            route = "PORTFOLIO_EXCEPTION"
            route_label = "Portfolio Exception"
            verdict_reason = (
                f"Missed hard cutoff ({'; '.join(reasons)}), but {match_pct}% of must-have skills "
                f"are backed by strong verified projects — nominated for Coordinator Cutoff Waiver."
            )
        elif alt_matches:
            route = "REROUTED"
            route_label = "Auto-Rerouted"
            best = alt_matches[0]
            verdict_reason = (
                f"Ineligible ({'; '.join(reasons)}). Auto-rerouted to "
                f"{best['company']} — {best['role']} ({best['fitPct']}% skill fit)."
            )
        else:
            route = "REROUTED"
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

    recommended_courses = build_youtube_courses(extracted, missing_must_have)

    routing = {
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
        "recommendedCourses": recommended_courses,
        "erpVerification": erp,
    }
    routing["credibility"] = compute_credibility_score(extracted, routing, erp, skill_test)
    return routing


TEST_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "questions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "skill": {"type": "STRING"},
                    "question": {"type": "STRING"},
                    "options": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "correctIndex": {"type": "INTEGER"},
                    "explanation": {"type": "STRING"},
                },
                "required": ["id", "skill", "question", "options", "correctIndex", "explanation"],
            },
        }
    },
    "required": ["questions"],
}

_FALLBACK_BANK: dict[str, list[dict[str, Any]]] = {
    "docker": [
        {
            "skill": "Docker",
            "question": "Which Dockerfile instruction defines the default executable run when a container starts and can be overridden at `docker run`?",
            "options": ["RUN", "CMD", "COPY", "EXPOSE"],
            "correctIndex": 1,
            "explanation": "CMD sets default command arguments that can be overridden when starting the container.",
        },
        {
            "skill": "Docker",
            "question": "In Docker Compose, how do two containers on the same default network communicate cleanly?",
            "options": [
                "By hardcoded host 127.0.0.1",
                "By the service name defined in docker-compose.yml",
                "By reading /etc/passwd",
                "Only via SSH",
            ],
            "correctIndex": 1,
            "explanation": "Compose provides built-in DNS resolution by service name.",
        },
    ],
    "rest apis": [
        {
            "skill": "REST APIs",
            "question": "Which HTTP status code is most appropriate when a POST endpoint successfully creates a new resource?",
            "options": ["200 OK", "201 Created", "204 No Content", "400 Bad Request"],
            "correctIndex": 1,
            "explanation": "201 Created indicates a new resource was created on the server.",
        },
        {
            "skill": "REST APIs",
            "question": "In FastAPI, what validates incoming JSON request bodies automatically using Python type hints?",
            "options": ["Pydantic BaseModel", "os.environ", "pickle.loads", "HTMLParser"],
            "correctIndex": 0,
            "explanation": "FastAPI uses Pydantic models for request validation and OpenAPI schema generation.",
        },
    ],
    "kubernetes": [
        {
            "skill": "Kubernetes",
            "question": "Which Kubernetes object ensures a specified number of Pod replicas are running and handles rolling updates?",
            "options": ["ConfigMap", "Deployment", "Ingress", "Secret"],
            "correctIndex": 1,
            "explanation": "A Deployment manages ReplicaSets and declarative rolling updates for Pods.",
        },
    ],
}


def _call_gemini_json(
    api_key: str,
    parts: list[dict[str, Any]],
    schema: dict[str, Any],
    temperature: float = 0.1,
) -> dict[str, Any]:
    """Shared Gemini API caller with retry and Flash model fallback."""
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY. Set your key in Settings first.")

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "responseSchema": schema,
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
                return {"data": parsed, "modelUsed": model, "attemptsLog": attempts_log}
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


def call_gemini_audit(
    api_key: str,
    jd: dict[str, Any],
    pdf_base64: str | None = None,
    resume_text: str | None = None,
) -> dict[str, Any]:
    """Call Gemini API directly with retry + model fallback and strict JSON schema."""
    instruction = (
        "You are PlaceFlow AI, a strict Campus Placement Cell Resume Verification Auditor.\n"
        "Analyze the student's resume against the target Job Description (JD) below.\n"
        "CRITICAL VERIFICATION RULES:\n"
        "1. Extract exact student_name, email, branch (e.g., CSE, ISE, ECE, AIML, EEE, MECH), cgpa (numeric), active_backlogs (integer, 0 if not listed/none), graduation_year.\n"
        "2. `verified_skills`: ONLY include a skill if there is concrete evidence in a Project, Internship, or Work Experience bullet proving they actually used it. Quote the specific project/internship in `evidence_source`.\n"
        "3. `unverified_claims`: Any technical skill listed in a Skills/Summary section that has ZERO mention or proof inside Projects/Experience MUST go here with a clear `reason`.\n"
        "4. `missing_must_have_skills`: List all JD must-have skills not present in `verified_skills`.\n"
        "5. `upskilling_plan_7_days`: Provide 3 concise actionable steps (e.g. Day 1-2, Day 3-4, Day 5-7) to close missing skills or build proof for unverified skills, including a specific `youtube_query` (e.g. 'FastAPI REST API Python full course tutorial') for each step.\n"
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

    res = _call_gemini_json(api_key, parts, RESPONSE_SCHEMA, temperature=0.1)
    return {
        "extracted": res["data"],
        "modelUsed": res["modelUsed"],
        "attemptsLog": res["attemptsLog"],
    }


def build_jd_prep_plan(extracted: dict[str, Any], target_jd: dict[str, Any]) -> dict[str, Any]:
    """Build a personalized preparation roadmap and YouTube courses for a chosen JD."""
    verified_names = [
        str(v.get("skill", "")).strip()
        for v in extracted.get("verified_skills", [])
        if v.get("skill")
    ]
    must_have = target_jd.get("mustHaveSkills", [])
    missing = [s for s in must_have if not _skill_matches(verified_names, s)]

    prep_steps: list[dict[str, str]] = []
    target_list = missing if missing else must_have[:2]
    day_buckets = ["Day 1-2", "Day 3-4", "Day 5-7"]
    for idx, skill in enumerate(target_list[:3]):
        _, query = SKILL_COURSE_CATALOG.get(
            skill.strip().lower(),
            (f"{skill} Full Course", f"{skill} full course project tutorial"),
        )
        prep_steps.append(
            {
                "day": day_buckets[idx],
                "focus_topic": f"Master {skill} Fundamentals & Patterns",
                "mini_task": f"Watch the linked {skill} course, build 1 verifiable mini-project for {target_jd.get('role')}, and pass the AI Skill Verification Test.",
                "youtube_query": query,
                "youtube_url": _youtube_search_url(query),
            }
        )

    fake_extracted = {
        "upskilling_plan_7_days": prep_steps,
        "unverified_claims": extracted.get("unverified_claims", []),
    }
    courses = build_youtube_courses(fake_extracted, missing or must_have[:2])
    total_req = max(len(must_have), 1)
    fit_pct = round(((total_req - len(missing)) / total_req) * 100)

    return {
        "jd": target_jd,
        "fitPct": fit_pct,
        "missingSkills": missing,
        "prepSteps": prep_steps,
        "recommendedCourses": courses,
    }


def generate_skill_test(
    api_key: str,
    student_name: str,
    target_jd: dict[str, Any],
    skills: list[str],
    courses: list[dict[str, str]],
) -> dict[str, Any]:
    """Generate a 5-question AI assessment tailored to lacking skills & YouTube course topics."""
    focus_skills = skills or target_jd.get("mustHaveSkills", [])[:2]
    course_titles = [c.get("courseTitle", c.get("skill", "")) for c in courses]

    if api_key:
        prompt = (
            "You are a technical interviewer creating a 5-question multiple-choice verification test.\n"
            f"Candidate: {student_name}\n"
            f"Target Role: {target_jd.get('company')} — {target_jd.get('role')}\n"
            f"Skills to Verify: {', '.join(focus_skills)}\n"
            f"Study Topics from Assigned YouTube Courses: {', '.join(course_titles)}\n\n"
            "Generate EXACTLY 5 practical scenario-based multiple-choice questions (4 options each, 0-based `correctIndex`). "
            "Test applied engineering understanding rather than trivia."
        )
        try:
            res = _call_gemini_json(api_key, [{"text": prompt}], TEST_SCHEMA, temperature=0.3)
            qs = res["data"].get("questions", [])[:5]
            if len(qs) >= 3:
                return {"questions": qs, "source": f"Gemini ({res['modelUsed']})"}
        except Exception:
            pass

    # Deterministic fallback if API unavailable/offline
    questions: list[dict[str, Any]] = []
    idx = 1
    for sk in focus_skills:
        for item in _FALLBACK_BANK.get(sk.strip().lower(), []):
            questions.append({"id": f"q{idx}", **item})
            idx += 1
    while len(questions) < 5:
        sk = focus_skills[len(questions) % max(len(focus_skills), 1)] if focus_skills else "Backend Engineering"
        questions.append(
            {
                "id": f"q{idx}",
                "skill": sk,
                "question": f"When building a production project using {sk} for {target_jd.get('company')}, which practice best proves reliability?",
                "options": [
                    f"Writing automated tests, error handling, and documented examples with {sk}",
                    "Listing the keyword in a resume header without code",
                    "Hardcoding secrets directly in frontend files",
                    "Skipping version control entirely",
                ],
                "correctIndex": 0,
                "explanation": f"Verified projects demonstrate working code, tests, and documentation in {sk}.",
            }
        )
        idx += 1
    return {"questions": questions[:5], "source": "PlaceFlow Local Question Bank"}


def grade_skill_test(
    questions: list[dict[str, Any]],
    answers: list[int],
    proctoring: dict[str, Any],
) -> dict[str, Any]:
    """Grade student skill verification test and record proctoring integrity."""
    total = max(len(questions), 1)
    correct = 0
    review: list[dict[str, Any]] = []
    verified_skills: list[str] = []

    for i, q in enumerate(questions):
        chosen = answers[i] if i < len(answers) else -1
        is_right = chosen == q.get("correctIndex")
        if is_right:
            correct += 1
            sk = str(q.get("skill") or "").strip()
            if sk and sk not in verified_skills:
                verified_skills.append(sk)
        review.append(
            {
                "id": q.get("id"),
                "skill": q.get("skill"),
                "correct": is_right,
                "chosen": chosen,
                "correctIndex": q.get("correctIndex"),
                "explanation": q.get("explanation"),
            }
        )

    score_pct = round((correct / total) * 100)
    tab_switches = int(proctoring.get("tabSwitches") or 0)
    passed = score_pct >= 60 and tab_switches <= 2

    return {
        "scorePct": score_pct,
        "correctCount": correct,
        "totalQuestions": total,
        "passed": passed,
        "verifiedSkills": verified_skills if passed else [],
        "proctoring": {
            "webcamActive": bool(proctoring.get("webcamActive")),
            "micActive": bool(proctoring.get("micActive")),
            "micAudioDetected": bool(proctoring.get("micAudioDetected")),
            "tabSwitches": tab_switches,
            "durationSec": int(proctoring.get("durationSec") or 0),
        },
        "review": review,
    }
