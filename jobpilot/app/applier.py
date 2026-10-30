"""Fill and (optionally) submit application forms on Greenhouse and Lever with Playwright.

Rule: anything the bot is not sure about -> stop and hand the job to a human.
Returns (status, note):
  applied      submitted, success page detected
  ready        form fully filled, waiting for your approval (dry-run mode)
  needs_human  captcha / unanswered required question / unexpected page
  failed       technical error
"""
import re

from . import config, llm
from .runner import RUN, Stopped

LABEL_JS = """el => {
  let t = '';
  if (el.id) { const l = document.querySelector('label[for="' + el.id + '"]'); if (l) t += l.innerText + ' '; }
  const p = el.closest('label'); if (p) t += p.innerText + ' ';
  const g = el.closest('.field, .application-field, .application-question, li, div');
  if (!t.trim() && g) { const lab = g.querySelector('label'); if (lab) t += lab.innerText + ' '; }
  return (t + ' ' + (el.getAttribute('aria-label')||'') + ' ' + (el.placeholder||'') + ' ' + (el.name||'')).trim();
}"""

FIELD_MAP = [
    (r"first.?name", "first_name"),
    (r"last.?name|surname|family name", "last_name"),
    (r"full.?name|^name\b|your name", "full_name"),
    (r"e-?mail", "email"),
    (r"phone|mobile|contact number|whatsapp", "phone"),
    (r"linked.?in", "linkedin"),
    (r"github", "github"),
    (r"portfolio|website|personal site|personal url|^url\b", "website"),
    (r"notice.?period|how soon can you join|availability to join|joining", "notice_period"),
    (r"expected (ctc|salary|compensation|pay)|salary expectation|desired (ctc|salary)", "expected_ctc"),
    (r"current (ctc|salary|compensation|pay)|present (ctc|salary)", "current_ctc"),
    (r"current (company|employer)|\borg\b|employer|organisation|organization", "current_company"),
    (r"current (title|designation|role)|job title|designation", "current_title"),
    (r"current (location|city)|location|city|prefer.*location", "location"),
    (r"total.?experience|years.?of.?experience|experience.?years", "years_experience"),
]
COVER = re.compile(r"cover letter|additional information|why .*(join|interested)|anything else", re.I)


def _value_for(label, p):
    low = label.lower()
    for pat, key in FIELD_MAP:
        if re.search(pat, low):
            if key == "full_name":
                return f"{p.get('first_name','')} {p.get('last_name','')}".strip()
            if key == "years_experience":
                y = p.get("years_experience")
                return str(y) if y not in (None, "") else ""
            return str(p.get(key, "") or "")
    return None


def _cover_note(profile, job):
    out = llm.complete(
        "You write short, honest, specific cover notes. Max 110 words. No fluff, no invented facts.",
        f"Candidate: {profile.get('summary')} Skills: {', '.join(profile.get('skills', [])[:25])}. "
        f"Experience years: {profile.get('years_experience')}.\n"
        f"Job: {job['title']} at {job['company']}.\n{(job.get('description') or '')[:1500]}\n"
        "Write the cover note.",
        400,
    )
    return out or ""


def apply(job, profile, resume_path, submit, sessions=None):
    """Greenhouse / Lever forms with their own browser; Indian portals through a shared logged-in session."""
    from . import portals

    if job.get("ats") in portals.PORTALS:
        portal = portals.PORTALS[job["ats"]]
        return portals.apply(portal, sessions.get(portal), job, resume_path, submit)
    if job.get("ats") not in ("greenhouse", "lever", "ashby"):
        return "needs_human", "External site - open the link and apply manually."
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "failed", "Playwright not installed. Run: pip install playwright && playwright install chromium"

    url = job["url"]
    if job["ats"] == "lever" and not url.rstrip("/").endswith("/apply"):
        url = url.rstrip("/") + "/apply"
    # Ashby often serves the form on the same jobUrl; no forced suffix
    shot = config.SHOTS / f"job_{job['id']}.png"
    unanswered = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=config.HEADLESS)
            page = browser.new_context(viewport={"width": 1280, "height": 1800}).new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            RUN.wait_page(page, 3000)

            # Greenhouse job page may need the Apply button / anchor first
            if page.locator("form").count() == 0:
                btn = page.locator("a:has-text('Apply'), button:has-text('Apply')").first
                if btn.count():
                    btn.click()
                    RUN.wait_page(page, 3000)
            if page.locator("form").count() == 0:
                browser.close()
                return "needs_human", "Could not find the application form."

            if page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .cf-turnstile, .h-captcha").count():
                # invisible reCAPTCHA is common; visible challenge appears only at submit
                pass

            fields = page.locator(
                "form input:not([type=hidden]):not([type=file]):not([type=submit]):not([type=checkbox]):not([type=radio]), "
                "form textarea, form select"
            ).all()
            for el in fields:
                RUN.check()
                try:
                    if not el.is_visible():
                        continue
                    label = el.evaluate(LABEL_JS)
                    required = (
                        el.get_attribute("required") is not None
                        or el.get_attribute("aria-required") == "true"
                        or "*" in label or "✱" in label
                    )
                    tag = el.evaluate("e => e.tagName.toLowerCase()")
                    if tag == "select":
                        if required and not el.input_value():
                            unanswered.append(label[:80])
                        continue
                    if el.input_value():
                        continue
                    val = _value_for(label, profile)
                    if val is None and tag == "textarea" and COVER.search(label):
                        val = _cover_note(profile, job)
                    if val:
                        el.fill(val)
                    elif required:
                        unanswered.append(label[:80])
                except Exception:
                    continue

            # required checkboxes / radios the bot will not guess
            for grp in page.locator("form [aria-required='true'][type=checkbox], form [required][type=radio]").all():
                try:
                    if grp.is_visible() and not grp.is_checked():
                        unanswered.append((grp.evaluate(LABEL_JS) or "checkbox/radio")[:80])
                except Exception:
                    continue

            files = page.locator("form input[type=file]")
            if files.count() and resume_path:
                files.first.set_input_files(resume_path)
                RUN.wait_page(page, 2500)

            unanswered = list(dict.fromkeys(u for u in unanswered if u))
            page.screenshot(path=str(shot), full_page=True)

            if unanswered:
                browser.close()
                return "needs_human", "Needs your answers: " + "; ".join(unanswered[:6])

            if not submit:
                browser.close()
                return "ready", "Form filled. Review screenshot, then press Approve & submit."

            page.locator("form button[type=submit], form input[type=submit], button:has-text('Submit')").first.click()
            RUN.wait_page(page, 6000)
            page.screenshot(path=str(shot), full_page=True)
            body = page.inner_text("body").lower()
            browser.close()
            if re.search(r"thank you|application (has been )?(submitted|received)|successfully submitted|we.?ve received", body):
                return "applied", "Submitted successfully."
            return "needs_human", "Submitted but no success page detected (captcha or validation?). Check screenshot."
    except Stopped:
        raise
    except Exception as e:
        return "failed", f"Browser error: {str(e)[:200]}"
