# PlaceFlow AI — Intelligent Placement Cell Resume-to-JD Verification & Skill-Gap Auto-Router

**SYNCHRONISE 2026 (Department of ISE, Ramaiah Institute of Technology) · Domain: Campus Automation (`PS-CA4`)**

PlaceFlow AI is an end-to-end automated placement suite (not a standalone prompt wrapper) with **3 isolated portals** (College Placement Cell, HR Recruiter, and Student), **College ERP Academic Verification**, **YouTube Skill Roadmaps**, and **Webcam/Mic AI-Proctored Skill Verification Tests**.

## 3-Portal Role-Based Access Control
1. **College Placement Cell (`admin@rit.edu` / `RIT-COLLEGE-2026`):**
   - Multimodal Gemini PDF verification (`inlineData` + 12-field `responseSchema`) with automatic Flash model fallback.
   - **College ERP Verification (`erp_db.py`):** Cross-checks resume CGPA, Semester, Branch, and Backlogs against official College ERP records.
   - **4-Track Auto-Router:** `Shortlisted`, `Portfolio Exception` (Cutoff Waiver), `Upskill Track`, and `Cross-JD Auto-Reroute`.
   - **Branch Stats & Analytics:** Branchwise shortlists, resume acceptance rate % per branch, and top lacking personal skills.
2. **HR / Recruiter Portal (`hr@cloudbackend.com` / `RIT-HR-2026`):**
   - Inspects verified candidates with a **0–100 Credibility Score** (ERP match + Project proof + Zero buzzwords + Proctored test bonus), branch filtering, and HR Shortlist CSV export.
3. **Student Portal (`<student>@rit.edu`, e.g. `ananya.rao@rit.edu` / `RIT-STUDENT-2026`):**
   - Displays personal ERP profile & application status, **Campus Opportunities & Full JD Viewer**, **"Prepare for Specific JD"** roadmaps with curated **YouTube course links**, and a **Webcam + Mic AI-Proctored Skill Test** that verifies lacking skills upon passing.

## Quick Start (Zero Dependencies — Python 3.10+)
1. Run `python3 server.py` (or double-click `start.command` on macOS / `start_windows.bat` on Windows).
2. Open `http://127.0.0.1:8765` in Chrome.
3. Sign in as **College** → click **Set Gemini Key** → **Load 5 Sample RIT PDFs** → **Verify & Route Batch**.
4. Open extra Chrome tabs to test **HR Recruiter** and **Student** portals simultaneously.

## Project Structure
- `server.py` — Zero-dependency HTTP server (`127.0.0.1:8765`) with 3-role RBAC APIs
- `erp_db.py` — College Academic ERP Database & HR Credibility Score engine
- `router_engine.py` — Gemini audit client, deterministic rules, YouTube course resolver, and AI skill test generator/grader
- `static/index.html` — Role-isolated UI for College, HR, and Student portals (Light/Dark mode)
- `sample_resumes/` — 5 realistic RIT sample `.pdf` resumes
- `test_server.py` — Automated verification tests (`python3 test_server.py`)
