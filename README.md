# AICTE Sentinel — Integrated Institution Complaint Monitoring Dashboard

A student-project prototype for centralized complaint monitoring, cross-bureau coordination, AI-assisted similarity screening, audit history, and CSV reporting.

**Important:** This is an independent prototype, not an official AICTE service. All preloaded cases and institutions are fictional demo data. Do not upload real personal, confidential, or government complaint data without formal authorization and a security review.

## Features
- Responsive, government-inspired dashboard UI
- Login for demo access
- Case register, search, and filters
- Institution ID and bureau-based overlap detection
- AI-assisted complaint text similarity:
  - Attempts to use `sentence-transformers` model `all-MiniLM-L6-v2`
  - Falls back to TF-IDF lexical similarity if the model cannot load
- Potential-overlap review workflow: confirm related / not related
- Chronological case action history
- SLA/overdue indicator
- Bureau/status summary reports
- CSV export for backup
- SQLite local database by default; PostgreSQL support through `DATABASE_URL`
- Health endpoint at `/health`

## Demo login
- Username: `demo`
- Password: `Demo@12345`

Change the password before any deployment by setting the `DEMO_PASSWORD` environment variable **before the first database initialization**. For a public deployment, disable or replace the demo account and implement organization-approved identity management.

## Run locally (Windows)
1. Install Python 3.11 or later.
2. Extract the ZIP.
3. Open a terminal in the extracted project folder.
4. Create a virtual environment:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
5. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
6. Run:
   ```powershell
   python app.py
   ```
7. Open `http://127.0.0.1:5000`.
8. Sign in with the demo login above.

The first semantic-model scan may download a model from Hugging Face and can take time. Internet access is required for the first download. If model installation/loading fails, the system uses its TF-IDF fallback and reports this in the alert reason. For a live jury demo, run at least one AI scan before the event so the model is already cached.

## How to demonstrate the AI
1. Open the demo dashboard.
2. Open case `PGRC-2026-001`.
3. Click **Run overlap scan**.
4. It should identify `RB-2026-014` because both have the same fictional institution ID and are assigned to different bureaus.
5. Open **Overlap Alerts** and review the reason/score.
6. Mark the alert as confirmed related or not related. The decision is recorded.
7. Add a new fictional case with a different wording to test text similarity.

A similarity score is **not** a probability and does not prove duplication. Thresholds are demonstration defaults and must be calibrated with representative, authorized test data. Same institution does not mean same complaint; officials must review every alert.

## Persistence and no-data-loss guidance
- Local default: SQLite at `instance/aicte_demo.db`. It persists between app restarts on the same computer.
- Use **Export CSV** regularly for a readable case-data backup.
- For a real multi-user deployment, use PostgreSQL and configure automated backups / point-in-time recovery with the database provider.
- Do not rely on an ephemeral web host filesystem for SQLite. Many hosting platforms replace ephemeral files on redeploy/restart.
- Keep at least one separate backup and test restoring it.
- Use `SECRET_KEY` as a strong environment secret. Do not commit credentials.
- HTTPS, role-based access, audit retention, encrypted backups, rate limiting, CSRF protection, security testing, and institutional approval are required before production use.

## Deploy to Render (public clickable HTTPS URL)
The easiest beginner workflow:
1. Create a GitHub account if you do not have one.
2. Create a **private** GitHub repository and upload these project files. Never commit `.env`, real complaint data, or database files.
3. In Render, create a managed PostgreSQL database. Copy its **internal database URL** for a web service in the same Render region.
4. In Render, choose **New + → Web Service**, connect the GitHub repository.
5. Runtime: Python. Build command: `pip install -r requirements.txt`. Start command: `gunicorn app:app`.
6. Add environment variables:
   - `SECRET_KEY`: a long random secret
   - `DATABASE_URL`: PostgreSQL connection URL
   - `DEMO_PASSWORD`: a strong password
   - `COOKIE_SECURE`: `1` after HTTPS is enabled
7. Deploy and wait for the service URL such as `https://your-service-name.onrender.com`.
8. Test `/health`, login, adding a case, AI scan, and CSV export.
9. In your PPT/Word report, insert the exact deployed HTTPS URL as a hyperlink. In PowerPoint, select text → Ctrl+K → paste URL. In Word, select text → Ctrl+K → paste URL. The same URL can be opened on Android or laptop.
10. Use a managed database with backups; do not use local SQLite for a public deployment.

Render pricing, disk policies, and managed database retention can change. Check the current plan before deployment. A public link makes the demo accessible but does not make it an official government website.

## AI design
1. Exact AICTE Permanent ID matching has priority.
2. Institution-name similarity can help find spelling/abbreviation variations.
3. Sentence Transformers compares complaint descriptions by meaning when available.
4. Candidate overlaps are stored as alerts for human review.
5. The officer's decision is logged; AI never closes, transfers, or disposes a case automatically.

## Known prototype limitations
- Demo authentication is intentionally simple; not production identity management.
- This prototype does not connect to AICTE systems or official records.
- No email/SMS gateway is configured.
- No document upload is enabled.
- Similarity thresholds require calibration and false-positive testing.
- Review the security checklist before any real deployment.
