"""India-only filtering: location gate, work mode, company tier/type, experience."""
import json
import re

from .config import DATA

CITY_GROUPS = {   # canonical name -> words that mean the same place
    "Bengaluru": ["bengaluru", "bangalore", "bengalore"],
    "Chennai": ["chennai", "madras"],
    "Hyderabad": ["hyderabad", "secunderabad", "hitec city"],
    "Pune": ["pune", "pimpri", "hinjewadi"],
    "Mumbai": ["mumbai", "navi mumbai", "thane", "bombay"],
    "Delhi NCR": ["delhi", "new delhi", "gurgaon", "gurugram", "noida", "greater noida", "ghaziabad", "faridabad", "ncr"],
    "Kolkata": ["kolkata", "calcutta", "howrah"],
    "Coimbatore": ["coimbatore", "kovai"],
    "Kochi": ["kochi", "cochin", "ernakulam", "kakkanad"],
    "Thiruvananthapuram": ["thiruvananthapuram", "trivandrum", "technopark"],
    "Ahmedabad": ["ahmedabad", "gandhinagar"],
    "Jaipur": ["jaipur"], "Indore": ["indore"], "Chandigarh": ["chandigarh", "mohali", "panchkula"],
    "Madurai": ["madurai"], "Trichy": ["trichy", "tiruchirappalli", "tiruchirapalli"],
    "Mysuru": ["mysuru", "mysore"], "Mangaluru": ["mangaluru", "mangalore"],
    "Visakhapatnam": ["visakhapatnam", "vizag"], "Nagpur": ["nagpur"], "Lucknow": ["lucknow"],
    "Bhubaneswar": ["bhubaneswar"], "Vadodara": ["vadodara", "baroda"], "Surat": ["surat"],
    "Bhopal": ["bhopal"], "Patna": ["patna"], "Dehradun": ["dehradun"], "Nashik": ["nashik"],
    "Salem": ["salem"], "Tirunelveli": ["tirunelveli"], "Vellore": ["vellore"], "Hosur": ["hosur"],
}
STATES = ["tamil nadu", "karnataka", "kerala", "telangana", "andhra pradesh", "maharashtra", "gujarat",
          "rajasthan", "uttar pradesh", "west bengal", "haryana", "punjab", "odisha", "madhya pradesh"]
CITY_PRESETS = list(CITY_GROUPS)[:12] + ["Remote"]

_ALL_WORDS = {w: c for c, ws in CITY_GROUPS.items() for w in ws}
_RX = re.compile(r"(?<![a-z])(" + "|".join(sorted(map(re.escape, _ALL_WORDS), key=len, reverse=True)) + r")(?![a-z])", re.I)

INDIA_PORTALS = {"naukri", "foundit", "shine", "internshala", "timesjobs", "apna"}

DEFAULT_PREFS = {
    "roles": [],
    "locations": [],                       # e.g. ["Chennai", "Bengaluru", "Remote"]; empty = all India
    "work_modes": ["remote", "hybrid", "wfo"],
    "company_tiers": ["tier1", "tier2", "tier3"],
    "company_types": ["startup", "mnc", "product", "service"],
    "exclude_keywords": ["intern ", "internship", "unpaid", "director", "vice president", "vp "],
    "portals": ["naukri", "foundit", "shine", "internshala"],  # all auto portals by default
    "include_career_pages": True,          # 120+ company Greenhouse/Lever/Ashby boards — highest auto-apply rate
    "min_score": 55,
    "daily_cap": 25,
    "auto_submit": True,                   # full auto: fills forms + submits (set false for review mode)
    "experience_years": None,
}


def _companies():
    try:
        return json.loads((DATA / "companies.json").read_text(encoding="utf-8"))
    except Exception:
        return {"boards": [], "classify": {}}


def load_boards():
    return _companies().get("boards", [])


def find_city(text):
    m = _RX.search(text or "")
    return _ALL_WORDS[m.group(1).lower()] if m else None


def is_india(job):
    loc = (job.get("location") or "").lower()
    if job.get("source") in INDIA_PORTALS or job.get("ats") in INDIA_PORTALS:
        return True
    if "india" in loc or find_city(loc) or any(s in loc for s in STATES):
        return True
    if not loc or loc.strip() in ("remote", "anywhere", "hybrid", "global", "worldwide"):
        # ambiguous: only keep it when the posting itself talks about India
        return bool(re.search(r"\bindia\b|\bIST\b|\b(?:₹|inr|lpa)\b", (job.get("description") or "")[:3000], re.I))
    return False


def work_mode(job):
    text = f"{job.get('title','')} {job.get('location','')} {(job.get('description') or '')[:3000]}".lower()
    if re.search(r"\bhybrid\b", text):
        return "hybrid"
    if job.get("remote") or re.search(r"\bremote\b|work from home|\bwfh\b|work-from-home", text):
        return "remote"
    return "wfo"


def classify_company(name):
    n = (name or "").lower()
    for frag, (tier, typ) in _companies().get("classify", {}).items():
        if frag in n:
            return tier, typ
    return "tier3", "unknown"      # unknown companies pass every company-type filter


def city_tier(city):
    t1 = {"Bengaluru", "Chennai", "Hyderabad", "Pune", "Mumbai", "Delhi NCR", "Kolkata"}
    return "tier1" if city in t1 else ("tier2" if city else "tier3")


def parse_exp(text):
    """'2-5 Yrs' -> (2, 5); 'Fresher' -> (0, 1); None if unknown."""
    t = (text or "").lower()
    m = re.search(r"(\d+)\s*(?:-|–|to)\s*(\d+)\s*(?:yrs?|years?)", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)\+?\s*(?:yrs?|years?)", t)
    if m:
        return int(m.group(1)), int(m.group(1)) + 3
    if re.search(r"\bfresher|\bentry level|0 ?years?", t):
        return 0, 1
    return None


def enrich(job):
    tier, typ = classify_company(job["company"])
    job["work_mode"] = work_mode(job)
    job["company_tier"], job["company_type"] = tier, typ
    city = find_city(job.get("location", "")) or find_city(job.get("description", "")[:600])
    job["city"] = city or ""
    if not job.get("location") and city:
        job["location"] = city
    return job


def _loc_match(job, wanted):
    hay = f"{job.get('location','')} {job.get('city','')}".lower()
    for w in wanted:
        if w.lower() in hay:
            return True
        for canon, words in CITY_GROUPS.items():
            if w.lower() == canon.lower() and any(x in hay for x in words):
                return True
    return False


def passes(job, prefs, years=None):
    title = f"{job['title'].lower()} "
    if any(k.lower() in title for k in prefs.get("exclude_keywords", [])):
        return False
    if not is_india(job):
        return False
    modes = prefs.get("work_modes") or []
    if modes and job["work_mode"] not in modes:
        return False
    if prefs.get("company_tiers") and job["company_tier"] not in prefs["company_tiers"]:
        return False
    types = prefs.get("company_types") or []
    if types and job["company_type"] not in types and job["company_type"] != "unknown":
        return False
    wanted = [l for l in prefs.get("locations", []) if l]
    places = [l for l in wanted if l.lower() != "remote"]
    if places:
        # remote roles are fine from any city; on-site / hybrid roles must be in a chosen city
        if job["work_mode"] != "remote" and not _loc_match(job, places):
            return False
    if years is not None:
        rng = parse_exp(job.get("exp") or "") or parse_exp((job.get("description") or "")[:1200])
        if rng and not (rng[0] - 1 <= years <= rng[1] + 2):
            return False
    return True
