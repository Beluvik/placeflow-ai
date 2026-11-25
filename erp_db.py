"""Mock College Academic ERP Database & Credibility Scoring Engine."""

from typing import Any

# Official College Academic Records (Source of Truth for CGPA, Semester, Branch, Backlogs)
COLLEGE_ERP_DB: dict[str, dict[str, Any]] = {
    "aarav.sharma@rit.edu": {
        "usn": "1MS23CS001",
        "name": "Aarav Sharma",
        "branch": "CSE",
        "semester": 7,
        "cgpa": 8.72,
        "active_backlogs": 0,
        "graduation_year": 2027,
    },
    "rohan.verma@rit.edu": {
        "usn": "1MS23CS042",
        "name": "Rohan Verma",
        "branch": "CSE",
        "semester": 7,
        "cgpa": 7.90,
        "active_backlogs": 0,
        "graduation_year": 2027,
    },
    "ananya.rao@rit.edu": {
        "usn": "1MS23IS014",
        "name": "Ananya Rao",
        "branch": "ISE",
        "semester": 7,
        "cgpa": 8.20,
        "active_backlogs": 0,
        "graduation_year": 2027,
    },
    "meera.nair@rit.edu": {
        "usn": "1MS23EC028",
        "name": "Meera Nair",
        "branch": "ECE",
        "semester": 7,
        "cgpa": 7.12,
        "active_backlogs": 0,
        "graduation_year": 2027,
    },
    "kiran.gowda@rit.edu": {
        "usn": "1MS23EC055",
        "name": "Kiran Gowda",
        "branch": "ECE",
        "semester": 7,
        "cgpa": 7.25,
        "active_backlogs": 0,
        "graduation_year": 2027,
    },
    "sneha.kulkarni@rit.edu": {
        "usn": "1MS23AI019",
        "name": "Sneha Kulkarni",
        "branch": "AIML",
        "semester": 7,
        "cgpa": 8.45,
        "active_backlogs": 0,
        "graduation_year": 2027,
    },
}


def verify_against_erp(
    email: str,
    resume_cgpa: float,
    resume_branch: str,
    resume_backlogs: int,
    claimed_semester: int | None = None,
) -> dict[str, Any]:
    """Verify resume academic claims against official College ERP database."""
    key = (email or "").strip().lower()
    record = COLLEGE_ERP_DB.get(key)
    if not record:
        return {
            "status": "INVALID",
            "verified": False,
            "registeredInErp": False,
            "usn": "UNREGISTERED",
            "officialCgpa": resume_cgpa,
            "officialSemester": claimed_semester or 7,
            "officialBranch": resume_branch,
            "officialBacklogs": resume_backlogs,
            "discrepancies": ["Student email not found in official College ERP directory."],
            "summary": "INVALID — Student email not found in official College ERP directory.",
        }

    discrepancies: list[str] = []
    if abs(float(record["cgpa"]) - float(resume_cgpa)) > 0.005:
        discrepancies.append(
            f"CGPA mismatch: Resume/input states {resume_cgpa}, ERP record shows {record['cgpa']}."
        )
    if record["branch"].upper() != (resume_branch or "").strip().upper():
        discrepancies.append(
            f"Branch mismatch: Resume/input states {resume_branch}, ERP shows {record['branch']}."
        )
    if int(record["active_backlogs"]) != int(resume_backlogs):
        discrepancies.append(
            f"Backlogs mismatch: Resume/input states {resume_backlogs}, ERP shows {record['active_backlogs']}."
        )
    if claimed_semester is not None and int(claimed_semester) != int(record["semester"]):
        discrepancies.append(
            f"Semester mismatch: Input states Sem {claimed_semester}, ERP shows Sem {record['semester']}."
        )

    is_clean = len(discrepancies) == 0
    return {
        "status": "VERIFIED" if is_clean else "INVALID",
        "verified": is_clean,
        "registeredInErp": True,
        "usn": record["usn"],
        "officialCgpa": record["cgpa"],
        "officialSemester": record["semester"],
        "officialBranch": record["branch"],
        "officialBacklogs": record["active_backlogs"],
        "discrepancies": discrepancies,
        "summary": (
            f"VERIFIED via College ERP ({record['usn']} · Sem {record['semester']} · CGPA {record['cgpa']})"
            if is_clean
            else f"INVALID — {'; '.join(discrepancies)}"
        ),
    }


def compute_credibility_score(
    extracted: dict[str, Any],
    routing: dict[str, Any],
    erp_check: dict[str, Any],
    skill_test: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute transparent 0-100 HR Credibility Score with itemized factors."""
    verified_count = len(extracted.get("verified_skills", []) or [])
    unverified_count = len(extracted.get("unverified_claims", []) or [])
    total_claimed = max(verified_count + unverified_count, 1)

    erp_pts = 35 if erp_check.get("verified") else 0
    proof_ratio = verified_count / total_claimed
    proof_pts = round(proof_ratio * 35)
    buzzword_pts = max(0, 20 - (unverified_count * 7))

    test_pts = 0
    if skill_test and skill_test.get("passed"):
        test_pts = 10
    elif routing.get("matchPct", 0) >= 80 and unverified_count == 0:
        test_pts = 10

    total = min(100, erp_pts + proof_pts + buzzword_pts + test_pts)
    tier = "High Trust" if total >= 80 else ("Moderate Trust" if total >= 55 else "Needs Audit")

    return {
        "score": total,
        "tier": tier,
        "breakdown": {
            "erpVerificationPts": erp_pts,
            "projectProofPts": proof_pts,
            "zeroBuzzwordPts": buzzword_pts,
            "skillValidationPts": test_pts,
        },
    }
