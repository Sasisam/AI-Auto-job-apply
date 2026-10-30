# JobPilot Pro — India multi-portal auto-apply

Upload your resume once. JobPilot searches **Naukri, foundit, Shine, Internshala** + **120+ company career pages** (Greenhouse / Lever / Ashby), scores each job against your resume, and **applies for you**.

**Target mix:** ~90% automatic apply (company sites + portal Easy Apply), ~10% manual (LinkedIn / Hirist / Indeed style sites whose terms forbid bots).

Runs on your own PC. Dashboard: http://127.0.0.1:8000

---

## What’s new in Pro

- **Professional dashboard** — clean sidebar filters, modern cards, clear match scores
- **Filters always visible** on Jobs page: Roles · Cities · Work style · Company size · Company type · Search on
- **Multi-portal by default** — Naukri + foundit + Shine + Internshala + company career pages
- **Only matching roles shown** — keyword + optional AI scoring
- **Full auto-apply** — select strong matches → Auto apply (or enable “Review before submit”)
- **Company own career pages** — Greenhouse / Lever / Ashby forms filled & submitted automatically

---

## Quick start

1. Install **Python 3.10+** (on Windows tick "Add to PATH").
2. **Windows:** double-click `run.bat`  
   **Mac / Linux:** `./run.sh`  
   First run installs dependencies (a few minutes). The dashboard opens automatically.
3. Open **Resume** → drop your PDF/DOCX → check name, email, phone, skills, notice period, CTC.
4. Open **Portals** → **Connect** Naukri (and foundit / Shine / Internshala) → log in in the browser window → press **I'm logged in**.
5. Open **Jobs** → set roles + cities + filters on the left → **Find jobs**.
6. Press **Select strong** → **Auto apply selected**.

Optional: put `ANTHROPIC_API_KEY` (better scoring + cover notes) and email/phone alerts in `.env`.

---

## What gets auto-applied (~90%)

| Source | How apply works |
|--------|-----------------|
| **Company career pages** (Greenhouse, Lever, Ashby) | Bot opens the form, fills fields from your resume, uploads CV, submits |
| **Naukri, foundit, Shine, Internshala** | Uses *your* logged-in browser; clicks Easy / Quick Apply |
| **Adzuna India** (optional free API key) | Extra listings; apply path depends on the employer site |

Fill **notice period**, **current CTC**, **expected CTC** in Resume so the bot can answer those common questions without stopping.

## What stays manual (~10%)

LinkedIn, Indeed, Instahyre, Cutshort, Hirist, Wellfound, TimesJobs, apna — JobPilot only opens a ready-made search. Their terms ban automation; automating them risks account bans. You apply yourself; mark "I applied" in the dashboard.

---

## Safety & control

- **Stop** button (top progress bar / bottom dock) halts search or auto-apply within 1–2 seconds.
- First week tip: turn on **Review before submit** in the bottom dock so the bot fills forms and waits for **Approve & submit**. Switch off when you trust it.
- Daily limit + random pauses protect portal accounts. Keep daily applications under ~30.
- Captcha, screening questions, or missing required fields → job goes to **Waiting**. The bot never invents answers.
- Portal logins stay only in `data/browser_profiles` on your PC. JobPilot never sees your password.

---

## Environment (`.env`)

```
ANTHROPIC_API_KEY=          # optional, better scoring + cover notes
AUTO_SUBMIT=true            # true ≈ full auto; false = approve each job
MIN_MATCH_SCORE=55
DAILY_APPLY_CAP=25
HEADLESS=true               # company forms
PORTAL_HEADLESS=false       # portals: visible window is safer
ADZUNA_APP_ID=              # optional free key
ADZUNA_APP_KEY=
```

Built for personal use on your machine. Use responsibly and respect each site's terms of service.
