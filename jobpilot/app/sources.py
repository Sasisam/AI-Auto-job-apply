"""Job sources that need no login: Adzuna India (optional free key) and the career pages of
Indian / India-hiring companies on Greenhouse / Lever / Ashby. Portals (Naukri, foundit, ...)
are handled in portals.py. This app is India-focused: non-India locations are filtered later."""
import html
import re

import requests

from . import config

UA = {"User-Agent": "Mozilla/5.0 (JobPilot personal job assistant)"}


def _clean(t):
    t = html.unescape(t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _get(url, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=20, **kw)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print("source error:", url[:60], e)
    return None


def adzuna(queries, locations):
    if not (config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY):
        return
    for q in queries:
        for loc in (locations or [""])[:2]:
            params = {"app_id": config.ADZUNA_APP_ID, "app_key": config.ADZUNA_APP_KEY,
                      "what": q, "results_per_page": 50, "max_days_old": 21}
            if loc and loc.lower() != "remote":
                params["where"] = loc
            data = _get("https://api.adzuna.com/v1/api/jobs/in/search/1", params=params)
            for j in (data or {}).get("results", []):
                yield {
                    "source": "adzuna", "ext_id": j["id"], "ats": "", "title": _clean(j["title"]),
                    "company": (j.get("company") or {}).get("display_name", ""),
                    "location": (j.get("location") or {}).get("display_name", "") + ", India",
                    "url": j["redirect_url"], "description": _clean(j.get("description")), "remote": False,
                }


def greenhouse(board):
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{board['slug']}/jobs", params={"content": "true"})
    for j in (data or {}).get("jobs", []):
        yield {
            "source": f"greenhouse:{board['slug']}", "ext_id": j["id"], "ats": "greenhouse",
            "title": j["title"], "company": board["name"],
            "location": (j.get("location") or {}).get("name", ""), "url": j["absolute_url"],
            "description": _clean(j.get("content")), "remote": False,
        }


def lever(board):
    data = _get(f"https://api.lever.co/v0/postings/{board['slug']}", params={"mode": "json"})
    for j in data or []:
        cats = j.get("categories") or {}
        yield {
            "source": f"lever:{board['slug']}", "ext_id": j["id"], "ats": "lever",
            "title": j["text"], "company": board["name"], "location": cats.get("location", ""),
            "url": j["hostedUrl"], "description": j.get("descriptionPlain") or _clean(j.get("description")),
            "remote": (j.get("workplaceType") or "").lower() == "remote",
        }


def ashby(board):
    """Ashby public job board API used by many modern product companies."""
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{board['slug']}")
    jobs = (data or {}).get("jobs") or []
    for j in jobs:
        loc = ""
        if j.get("location"):
            loc = j["location"]
        elif j.get("address") and isinstance(j["address"], dict):
            loc = j["address"].get("postalAddress", "") or j["address"].get("addressLocality", "")
        yield {
            "source": f"ashby:{board['slug']}", "ext_id": j.get("id") or str(j.get("jobUrl", ""))[-20:],
            "ats": "ashby", "title": j.get("title", ""), "company": board["name"],
            "location": loc, "url": j.get("jobUrl") or j.get("applyUrl") or "",
            "description": _clean(j.get("descriptionHtml") or j.get("descriptionPlain") or ""),
            "remote": (j.get("workplaceType") or j.get("isRemote") or False) in (True, "Remote", "remote"),
        }


def collect_open(profile, prefs, boards, check=lambda: None):
    """Adzuna + company career pages (Greenhouse / Lever / Ashby)."""
    roles = prefs.get("roles") or profile.get("target_roles") or []
    jobs = list(adzuna(roles[:8], prefs.get("locations")))
    if prefs.get("include_career_pages", True):
        for b in boards:
            check()
            fn = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}.get(b.get("ats"))
            if fn:
                try:
                    jobs += list(fn(b))
                except Exception as e:
                    print("board error:", b.get("name"), e)
    return jobs
