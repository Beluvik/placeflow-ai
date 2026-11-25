# PlaceFlow AI — Intelligent Placement Cell Resume-to-JD Verification & Skill-Gap Auto-Router

**SYNCHRONISE 2026 (Department of ISE, Ramaiah Institute of Technology) · Domain: Campus Automation (`PS-CA4`)**

PlaceFlow AI is an end-to-end automated placement screening pipeline (not a standalone prompt wrapper) combining **Gemini multimodal PDF verification** with a **deterministic Python rule engine** and **3-track Auto-Router**.

## Key Features
- **Multimodal Batch PDF Audit:** Sends raw student resume PDFs directly to Gemini (`inlineData` / `application/pdf`) using a strict 12-field `responseSchema`.
- **Buzzword vs. Proof Verification:** Distinguishes `verified_skills` (backed by real projects/internships) from `unverified_claims` (skills listed with zero supporting evidence).
- **Deterministic Cutoff Engine:** Pure Python checks for `CGPA >= minCgpa`, normalized `branch`, and `active_backlogs <= maxBacklogs`.
- **3-Track Auto-Router:**
  1. **Shortlisted:** Passes cutoffs and verified skill threshold → exported in the HR Shortlist `.csv`.
  2. **Upskill Track:** Passes cutoffs with skill gaps or unverified claims → assigned an interactive 7-day mini-project roadmap.
  3. **Cross-JD Auto-Reroute:** Fails primary cutoffs → automatically matched against other active company drives.
- **Fault-Tolerant Backend:** Sequential throttling, exponential backoff retries on `429`/`503`, and automatic model fallback (`gemini-3.8-flash` → `gemini-3.7-flash` → `gemini-3.6-flash` → `gemini-3.5-flash-lite`).

## Quick Start (Zero Dependencies — Python 3.10+)

### macOS
1. Double-click `start.command`, or run in Terminal:
   ```bash
   python3 server.py
   ```
2. Open `http://127.0.0.1:8765` in Chrome.
3. Click **Set Gemini Key** in the top-right bar and paste your Gemini API key (saved locally to `.env`, ignored by Git).
4. Click **Load 4 Sample RIT PDFs** → **Verify & Route Batch**.

### Windows / Linux
1. Run `start_windows.bat` (Windows) or in Command Prompt / Terminal:
   ```bash
   python server.py
   ```
2. Open `http://127.0.0.1:8765` in your browser.

## Project Structure
- `server.py` — Zero-dependency HTTP server (`127.0.0.1:8765`) & API routes
- `router_engine.py` — Gemini `RESPONSE_SCHEMA`, retry/fallback client, and deterministic auto-router
- `static/index.html` — Interactive 3-tab dashboard with Light/Dark mode and slide-over dossier drawer
- `sample_resumes/` — 4 realistic RIT sample `.pdf` resumes covering every routing track
- `test_server.py` — Automated verification tests (`python3 test_server.py`)
