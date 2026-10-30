"""Indian job portals, driven through YOUR OWN logged-in browser on YOUR PC.

How it works
  connect  -> opens the portal's login page in a window. You log in yourself (OTP / captcha included).
              JobPilot never sees or stores your password; the login stays in data/browser_profiles/<portal>.
  search   -> reads job links from the portal's search result pages.
  apply    -> opens the job, clicks the portal's own Apply button, reports what happened.

Portals change their layout now and then. Instead of fragile CSS class names this file finds jobs by
URL pattern (link_re) and buttons by their visible text, which survives most redesigns.
If a portal still breaks, only the PortalSpec for that portal below needs a tweak.

Portals marked auto=False (LinkedIn, Indeed, ...) forbid bots in their terms and ban accounts quickly.
JobPilot only gives you pre-filled search links for them.
"""
import random
import re
from dataclasses import dataclass, field
from urllib.parse import quote, quote_plus

from . import config
from .runner import RUN, Stopped, log


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


@dataclass
class Portal:
    id: str
    name: str
    login_url: str
    home_url: str
    search: object                      # fn(role, loc, years, page) -> url
    link_re: str                        # href pattern of a job detail page
    login_re: str = r"login|signin|sign-in|nlogin|auth|register"
    auto: bool = True
    blurb: str = ""
    apply_re: str = r"^\s*(easy apply|quick apply|apply now|apply|apply for (this )?job|1-click apply|one click apply)\s*$"
    external_re: str = r"company (site|website)|apply on (the )?(company|employer)|apply externally"
    already_re: str = r"^\s*(applied|already applied|application submitted|you have applied)\s*$"
    success_re: str = (
        r"successfully applied|applied successfully|you have (successfully )?applied|"
        r"application (has been )?(sent|submitted|received)|thank you for applying|application sent"
    )
    manual_url: object = None           # fn(role, loc) for link-only portals


PORTALS = {}


def _add(p):
    PORTALS[p.id] = p


def _naukri_search(role, loc, years, pg):
    path = slug(role) + "-jobs" + (f"-in-{slug(loc)}" if loc else "") + (f"-{pg}" if pg > 1 else "")
    return f"https://www.naukri.com/{path}?k={quote(role)}" + (f"&l={quote(loc)}" if loc else "") + f"&experience={years}"


_add(Portal(
    "naukri", "Naukri", "https://www.naukri.com/nlogin/login", "https://www.naukri.com/mnjuser/homepage",
    _naukri_search, r"/job-listings-", login_re=r"nlogin|login",
    blurb="India's biggest portal. One-click Apply.",
    apply_re=r"^\s*(apply|apply now|easy apply)\s*$",
    external_re=r"apply on company site|company site",
))
_add(Portal(
    "foundit", "foundit", "https://www.foundit.in/rio/login", "https://www.foundit.in/seeker/dashboard",
    lambda r, l, y, p: f"https://www.foundit.in/srp/results?query={quote_plus(r)}" + (f"&locations={quote_plus(l)}" if l else "")
    + f"&experienceRanges={y}~{y}&start={(p - 1) * 15}&limit=15",
    r"foundit\.in/job/|/job/[^?#]*-\d{5,}",
    blurb="Formerly Monster India. Good for IT and fresher roles.",
))
_add(Portal(
    "shine", "Shine", "https://www.shine.com/login/", "https://www.shine.com/myshine/",
    lambda r, l, y, p: f"https://www.shine.com/job-search/{slug(r)}-jobs" + (f"-in-{slug(l)}" if l else "") + (f"-{p}" if p > 1 else "")
    + f"?q={quote_plus(r)}" + (f"&loc={quote_plus(l)}" if l else ""),
    r"/jobs/[^?#]+/\d{6,}",
    blurb="HT Media portal. Strong for Tier-2 city jobs.",
))
_add(Portal(
    "internshala", "Internshala", "https://internshala.com/login/user", "https://internshala.com/student/dashboard",
    lambda r, l, y, p: f"https://internshala.com/jobs/{slug(r)}-jobs" + (f"-in-{slug(l)}" if l else "") + (f"/page-{p}" if p > 1 else ""),
    r"/job/detail/",
    blurb="Fresher jobs and internships. Often asks a question, so those wait for you.",
    apply_re=r"^\s*(apply now|apply|easy apply)\s*$",
))

# ---- link-only portals (terms forbid bots, so no automation) --------------
_manual = {
    "linkedin": ("LinkedIn", lambda r, l: f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(r)}&location={quote_plus(l or 'India')}&f_TPR=r604800"),
    "indeed": ("Indeed India", lambda r, l: f"https://in.indeed.com/jobs?q={quote_plus(r)}&l={quote_plus(l)}&fromage=7"),
    "instahyre": ("Instahyre", lambda r, l: f"https://www.instahyre.com/search-jobs/?job_title={quote_plus(r)}"),
    "cutshort": ("Cutshort", lambda r, l: f"https://cutshort.io/jobs?q={quote_plus(r)}"),
    "hirist": ("Hirist", lambda r, l: f"https://www.hirist.tech/search/{quote(r)}"),
    "wellfound": ("Wellfound", lambda r, l: f"https://wellfound.com/role/l/{slug(r)}/india"),
    "timesjobs": ("TimesJobs", lambda r, l: f"https://www.timesjobs.com/candidate/job-search.html?searchType=personalizedSearch&txtKeywords={quote_plus(r)}&txtLocation={quote_plus(l)}"),
    "apna": ("apna", lambda r, l: f"https://apna.co/jobs?search={quote_plus(r)}"),
}
for _id, (_name, _fn) in _manual.items():
    _add(Portal(_id, _name, "", "", None, "", auto=False, manual_url=_fn, blurb="Search link only (no automation)."))

AUTO_IDS = [p.id for p in PORTALS.values() if p.auto]


# ======================================================================
# browser session
# ======================================================================
class Session:
    """One persistent, logged-in browser window for one portal."""

    def __init__(self, portal, headless=None):
        self.portal = portal
        self.headless = config.PORTAL_HEADLESS if headless is None else headless
        self.pw = self.ctx = self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self.pw = sync_playwright().start()
        profile = config.BROWSER_PROFILES / self.portal.id
        profile.mkdir(exist_ok=True)
        self.ctx = self.pw.chromium.launch_persistent_context(
            str(profile), headless=self.headless, viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        self.ctx.set_default_timeout(15000)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *a):
        for fn in (lambda: self.ctx.close(), lambda: self.pw.stop()):
            try:
                fn()
            except Exception:
                pass
        return False

    def goto(self, url):
        RUN.check()
        self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        RUN.wait_page(self.page, 2500)


# ======================================================================
# connect (log in once)
# ======================================================================
def connect(pid):
    portal = PORTALS[pid]
    RUN.progress(0, 1, f"Login window: {portal.name}")
    with Session(portal, headless=False) as s:
        s.page.goto(portal.login_url, timeout=60000)
        log(f"{portal.name} window opened - log in there, then press 'I'm logged in' in JobPilot (10 min limit).")
        import time

        end, closed = time.time() + 600, False
        while time.time() < end and not RUN.done_event.is_set():
            RUN.check()
            time.sleep(1)
            try:
                if not s.ctx.pages:
                    closed = True
                    break
                _ = s.ctx.pages[0].url
            except Exception:
                closed = True
                break
        RUN.check()          # Stop pressed: leave without marking the portal as connected
        ok = True
        if not closed and RUN.done_event.is_set():
            try:
                s.page.goto(portal.home_url, timeout=45000)
                s.page.wait_for_timeout(2500)
                ok = not re.search(portal.login_re, s.page.url, re.I)
            except Exception:
                ok = True
        elif not closed:
            ok = False
    config.set_portal_connected(pid, ok)
    log(f"{portal.name} connected." if ok else f"{portal.name}: login not completed. Try Connect again.")
    return ok


# ======================================================================
# search
# ======================================================================
JS_LINKS = r"""(pat) => {
  const re = new RegExp(pat, 'i');
  const links = [...document.querySelectorAll('a[href]')].filter(a => re.test(a.href));
  const seen = new Set(), out = [];
  for (const a of links) {
    const href = a.href.split('#')[0];
    if (seen.has(href)) continue;
    seen.add(href);
    let card = a, best = a;
    for (let i = 0; i < 7 && card.parentElement; i++) {
      card = card.parentElement;
      const n = [...card.querySelectorAll('a[href]')].filter(x => re.test(x.href) && x.href.split('#')[0] !== href).length;
      if (n > 0 || card.innerText.length > 1600) break;
      best = card;
    }
    out.push({href, title: (a.innerText || a.title || '').trim(), text: best.innerText || ''});
  }
  return out;
}"""

EXP_RE = re.compile(r"(\d+\s*[-–to]+\s*\d+\s*(?:yrs?|years?)|fresher|\d+\+?\s*(?:yrs?|years?))", re.I)
SAL_RE = re.compile(r"((?:₹|rs\.?\s*)?[\d.,]+\s*[-–]\s*[\d.,]+\s*(?:lpa|lacs?(?: pa)?|lakhs?|k)|not disclosed|[\d.,]+\s*(?:lpa|lacs?))", re.I)


def _parse_card(portal, c):
    lines = [l.strip() for l in re.split(r"[\n\r]+", c["text"]) if l.strip()]
    title = c["title"] or (lines[0] if lines else "")
    rest = [l for l in lines if l != title and len(l) < 140]
    company = next((l for l in rest if not EXP_RE.search(l) and not SAL_RE.search(l) and len(l) > 1
                    and not re.match(r"^(posted|\d+ (day|hour|week)|new|apply|save|easy apply|be an early applicant)", l, re.I)), "")
    exp = EXP_RE.search(c["text"])
    sal = SAL_RE.search(c["text"])
    from .filters import find_city

    loc = find_city(c["text"]) or ""
    jid = re.sub(r"\D", "", c["href"].split("?")[0])[-12:] or slug(c["href"])[-40:]
    return {
        "source": portal.id, "ext_id": jid, "ats": portal.id, "title": title[:160],
        "company": (company or "Unknown")[:120], "location": loc,
        "url": c["href"].split("?")[0] if portal.id == "naukri" else c["href"],
        "description": " ".join(rest)[:1500], "exp": exp.group(1) if exp else "",
        "salary": sal.group(1) if sal else "", "remote": False,
    }


def search(portal, sess, profile, prefs, roles, max_roles=4, pages=3):
    years = int(float(profile.get("years_experience") or 0))
    locs = [l for l in (prefs.get("locations") or []) if l and l.lower() != "remote"][:2] or [""]
    out, seen = [], set()
    for role in roles[:max_roles]:
        for loc in locs:
            for pg in range(1, pages + 1):
                RUN.check()
                try:
                    sess.goto(portal.search(role, loc, years, pg))
                    sess.page.wait_for_function(
                        "pat => [...document.querySelectorAll('a[href]')].some(a => new RegExp(pat, 'i').test(a.href))",
                        arg=portal.link_re, timeout=12000,
                    )
                except Stopped:
                    raise
                except Exception:
                    log(f"{portal.name}: no results for '{role}' {loc} page {pg} (blocked, captcha or layout changed)")
                    break
                RUN.wait_page(sess.page, 1200)
                for _ in range(3):  # lazy-loaded lists
                    sess.page.mouse.wheel(0, 2500)
                    RUN.wait_page(sess.page, 500)
                n0 = len(out)
                for c in sess.page.evaluate(JS_LINKS, portal.link_re):
                    j = _parse_card(portal, c)
                    if not j["title"] or j["ext_id"] in seen:
                        continue
                    seen.add(j["ext_id"])
                    out.append(j)
                log(f"{portal.name}: '{role}' {loc or 'India'} p{pg} -> {len(out) - n0} jobs")
                RUN.sleep(random.uniform(2.5, 5))
    return out


# ======================================================================
# apply
# ======================================================================
def _find_button(page, pattern):
    rx = re.compile(pattern, re.I)
    for role in ("button", "link"):
        loc = page.get_by_role(role, name=rx)
        try:
            for i in range(min(loc.count(), 6)):
                el = loc.nth(i)
                if el.is_visible():
                    return el
        except Exception:
            continue
    return None


def _dialog_needs_input(page):
    """True if a pop-up form asks for something JobPilot should not guess."""
    sel = "[role=dialog] input:not([type=hidden]):not([type=checkbox]):not([type=file]), [role=dialog] textarea, [role=dialog] select, [class*=chatbot] input, [class*=modal] textarea"
    try:
        for el in page.locator(sel).all()[:12]:
            if el.is_visible() and not (el.input_value() or "").strip():
                return True
    except Exception:
        pass
    return False


def apply(portal, sess, job, resume_path, submit):
    """Returns (status, note)."""
    page = sess.page
    shot = config.SHOTS / f"job_{job['id']}.png"
    if not config.portal_connected(portal.id):
        return "needs_human", f"{portal.name} is not connected. Open Portals and log in once."
    try:
        sess.goto(job["url"])
        RUN.wait_page(page, 1500)
        if re.search(portal.login_re, page.url, re.I) or page.locator("input[type=password]:visible").count():
            config.set_portal_connected(portal.id, False)
            return "needs_human", f"{portal.name} login expired. Open Portals and connect again."
        body = page.inner_text("body")
        low = body.lower()
        if re.search(r"job (is )?(no longer|has been) (available|active)|this job has expired|position (has been )?closed|no longer accepting", low):
            return "skipped", "Job is closed or expired."
        if _find_button(page, portal.already_re):
            return "skipped", f"Already applied on {portal.name}."
        btn = _find_button(page, portal.apply_re)
        if not btn:
            page.screenshot(path=str(shot))
            if _find_button(page, portal.external_re):
                return "needs_human", "This job applies on the company's own website. Open the link."
            return "needs_human", "Apply button not found (job closed or portal layout changed)."
        page.screenshot(path=str(shot))
        if not submit:
            return "ready", f"Ready. Press Approve & submit to click Apply on {portal.name}."
        RUN.check()
        btn.click()
        for step in range(4):
            RUN.wait_page(page, 3000)
            body = page.inner_text("body").lower()
            if re.search(portal.success_re, body):
                page.screenshot(path=str(shot))
                return "applied", f"Applied on {portal.name}."
            if _dialog_needs_input(page):
                page.screenshot(path=str(shot))
                return "needs_human", f"{portal.name} is asking questions. Open the job, press Apply and answer them."
            nxt = None
            for dlg in page.locator("[role=dialog], [class*=modal]").all()[:3]:
                try:
                    nxt = dlg.get_by_role("button", name=re.compile(r"^\s*(submit|apply|continue|next|send application|confirm)", re.I))
                    if nxt.count() and nxt.first.is_visible():
                        nxt.first.click()
                        break
                    nxt = None
                except Exception:
                    nxt = None
            if not nxt:
                break
        page.screenshot(path=str(shot))
        if _find_button(page, portal.already_re):
            return "applied", f"Applied on {portal.name}."
        return "needs_human", "Clicked Apply but could not confirm it. Check the screenshot or the portal's Applied list."
    except Stopped:
        raise
    except Exception as e:
        return "failed", f"Browser error: {str(e)[:180]}"
