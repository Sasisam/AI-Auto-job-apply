"""Score how well a job fits the resume: cheap keyword score first, AI score on the best ones."""
import re

from . import llm

SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|head|manager|architect)\b", re.I)
JUNIOR = re.compile(r"\b(junior|jr\.?|fresher|entry|associate|trainee|graduate)\b", re.I)


def _has(text, term):
    return re.search(r"(?<![\w])" + re.escape(term) + r"(?![\w])", text) is not None


def title_fit(roles, title):
    """0..1 - how much of any searched role's words appear in the job title."""
    t = title.lower()
    best = 0.0
    for role in roles:
        words = [w for w in re.findall(r"[a-z+#.]+", role.lower()) if len(w) > 2]
        if words:
            best = max(best, sum(w in t for w in words) / len(words))
    return best


def keyword_score(profile, job, roles=None):
    skills = [s.lower() for s in profile.get("skills", [])]
    text = f"{job['title']} {job.get('description','')}".lower()
    matched = [s for s in skills if _has(text, s)]
    thin = len(text) < 700          # portal search cards carry little text
    denom = max(2, min(len(skills), 4)) if thin else max(5, min(len(skills), 12))
    skill_part = min(1.0, len(matched) / denom) * (35 if thin else 60)

    title = job["title"].lower()
    title_part = 0
    for role in (roles or profile.get("target_roles") or []):
        words = [w for w in re.findall(r"[a-z+#.]+", role.lower()) if len(w) > 2]
        if words:
            title_part = max(title_part, sum(w in title for w in words) / len(words) * (65 if thin else 40))

    score = skill_part + title_part
    years = float(profile.get("years_experience") or 0)
    if SENIOR.search(job["title"]) and years < 4:
        score -= 25
    if JUNIOR.search(job["title"]) and years > 6:
        score -= 15
    return {"score": int(max(0, min(100, score))), "matched": matched[:15], "reason": ""}


LLM_PROMPT = """Rate how well this candidate fits this job. Reply ONLY with JSON:
{"score": 0-100, "reason": "one short sentence", "apply": true/false}
Be strict: score above 75 only if the core skills AND experience level clearly match.

CANDIDATE: roles={roles}; years_experience={years}; skills={skills}; summary={summary}; education={edu}

JOB: {title} at {company} ({location})
{desc}"""


def llm_score(profile, job):
    if not llm.available():
        return None
    prompt = LLM_PROMPT.format(
        roles=profile.get("target_roles"), years=profile.get("years_experience"),
        skills=", ".join(profile.get("skills", [])[:40]), summary=profile.get("summary", ""),
        edu=profile.get("education", ""), title=job["title"], company=job["company"],
        location=job.get("location", ""), desc=(job.get("description") or "")[:3500],
    )
    return llm.complete_json("You are a strict technical recruiter.", prompt, 300)
