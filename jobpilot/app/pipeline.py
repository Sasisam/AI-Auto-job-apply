"""Search -> filter -> score (discover), then apply (auto, or after your click), then notify.
Every loop calls RUN.check()/RUN.sleep(), so the Stop button works within a second or two."""
import random
from datetime import datetime

from . import applier, config, db, filters, matcher, notify, portals, resume, sources
from .runner import RUN, Stopped, log


def effective_prefs(prefs):
    p = {**filters.DEFAULT_PREFS, **(prefs or {})}
    p["min_score"] = int(p.get("min_score") or config.MIN_MATCH_SCORE)
    p["daily_cap"] = int(p.get("daily_cap") or config.DAILY_APPLY_CAP)
    return p


class Sessions:
    """Keeps one logged-in browser window per portal open during a run, closes all at the end."""

    def __init__(self):
        self.open = {}

    def get(self, portal):
        if portal.id not in self.open:
            s = portals.Session(portal)
            s.__enter__()
            self.open[portal.id] = s
        return self.open[portal.id]

    def close(self):
        for s in self.open.values():
            s.__exit__()
        self.open.clear()


def _years(profile, prefs):
    y = prefs.get("experience_years")
    if y in (None, ""):
        y = profile.get("years_experience") or 0
    try:
        return int(float(y))
    except (TypeError, ValueError):
        return 0


def discover(uid=1):
    """Find jobs for the user's roles in India, filter, score, save. No applying."""
    user = db.get_user(uid)
    profile = user["profile"]
    if not profile or not (profile.get("skills") or profile.get("target_roles")):
        log("No resume yet - upload your resume first.")
        return 0
    prefs = effective_prefs(user["prefs"])
    roles = prefs.get("roles") or profile.get("target_roles") or []
    years = _years(profile, prefs)
    log(f"Searching India for: {', '.join(roles) or '(no roles)'}  |  experience {years} yr")
    RUN.progress(0, 1, "Searching job sources")

    raw = sources.collect_open(profile, prefs, filters.load_boards(), RUN.check)
    log(f"Company pages + Adzuna: {len(raw)} postings")

    sess = Sessions()
    try:
        for pid in prefs.get("portals", []):
            RUN.check()
            portal = portals.PORTALS.get(pid)
            if not portal or not portal.auto:
                continue
            if not config.portal_connected(pid):
                log(f"{portal.name}: not connected - skipped (connect it in Portals).")
                continue
            RUN.progress(current=f"Searching {portal.name}")
            try:
                raw += portals.search(portal, sess.get(portal), profile, prefs, roles)
            except Stopped:
                raise
            except Exception as e:
                log(f"{portal.name} search error: {str(e)[:150]}")
    finally:
        sess.close()

    added = 0
    for j in raw:
        RUN.check()
        j = filters.enrich(j)
        if not filters.passes(j, prefs, years):
            continue
        kw = matcher.keyword_score(profile, j, roles)
        if kw["score"] < 30:
            continue
        j.update(kw)
        if db.add_job(uid, j):
            added += 1
    log(f"{added} new matching jobs saved")

    pending = [x for x in db.jobs(uid, status="new") if not x["llm_scored"]][:40]
    for n, job in enumerate(pending):
        RUN.check()
        RUN.progress(n, len(pending), "AI scoring jobs")
        res = matcher.llm_score(profile, job)
        if res:
            blended = int(0.35 * job["score"] + 0.65 * float(res.get("score", job["score"])))
            db.set_job(job["id"], score=blended, reason=str(res.get("reason", ""))[:300], llm_scored=1)
        else:
            db.set_job(job["id"], llm_scored=1)
    log("Search finished")
    return added


def process_application(job_id, uid=1, submit=None, sessions=None):
    user = db.get_user(uid)
    prefs = effective_prefs(user["prefs"])
    job = db.get_job(job_id)
    if not job:
        return "failed"
    if submit is None:
        submit = bool(prefs.get("auto_submit") or config.AUTO_SUBMIT)
    who = f"{job['title']} @ {job['company']}"
    RUN.progress(current=who)

    rpath = resume.active_path(user["resume_path"])
    if not rpath:
        db.set_job(job_id, status="needs_human", note="No resume found. Upload one in My Resume.")
        log(f"NO RESUME    {who}")
        return "needs_human"
    if job.get("apply_mode") != "auto":
        db.set_job(job_id, status="manual", note="External site - open the link, apply, then press 'I applied'.")
        log(f"MANUAL       {who}")
        return "manual"

    before = job["status"]
    db.set_job(job_id, status="applying", note="Opening the page...")
    log(f"APPLYING     {who}")
    own = sessions is None
    sessions = sessions or Sessions()
    try:
        status, note = applier.apply(job, user["profile"], str(rpath), submit, sessions)
    except Stopped:
        db.set_job(job_id, status=before if before != "applying" else "new", note="Stopped by you before it finished.")
        raise
    finally:
        if own:
            sessions.close()
    fields = {"status": status, "note": note}
    if status in ("applied", "ready"):
        fields["applied_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        fields["applied_by"] = "ai"
    db.set_job(job_id, **fields)

    if status == "applied":
        notify.notify(f"Applied: {who}", f"Application submitted by JobPilot.\nMatch score: {job['score']}", link=job["url"])
    elif status == "ready":
        notify.notify(f"Ready to approve: {who}", "Form is filled. Open JobPilot and press Approve & submit.", link=job["url"])
    elif status in ("needs_human", "failed"):
        notify.notify(f"Need your help: {who}", note, urgent=True, link=job["url"])
    log(f"{status.upper():12} {who} - {note}")
    return status


def apply_batch(ids, uid=1, submit=False):
    """The 'Auto apply' button. One job at a time, with human-like pauses, stoppable at any moment."""
    RUN.progress(0, len(ids))
    sessions = Sessions()
    done = False
    try:
        for n, jid in enumerate(ids):
            RUN.check()
            RUN.progress(n, len(ids))
            st = process_application(jid, uid, submit, sessions)
            RUN.count(st)
            RUN.progress(n + 1, len(ids))
            if n < len(ids) - 1 and st in ("applied", "ready"):
                RUN.progress(current="Short pause (looks human, protects your account)")
                RUN.sleep(random.uniform(12, 30))
        done = True
    finally:
        sessions.close()
        summary = ("Auto-apply done: " if done else "Auto-apply stopped: ") + (
            ", ".join(f"{v} {k}" for k, v in RUN.counts.items() if v) or "nothing applied")
        RUN.last_summary = summary
        log(summary)
        if done:
            notify.notify("Auto-apply finished", summary)


def run_once(uid=1):
    """'Run now' / scheduled: discover, then auto-apply the best matches."""
    discover(uid)
    prefs = effective_prefs(db.get_user(uid)["prefs"])
    left = max(prefs["daily_cap"] - db.applied_today(uid), 0)
    todo = [x for x in db.jobs(uid, status="new") if x["score"] >= prefs["min_score"]]
    auto = [x["id"] for x in todo if x["apply_mode"] == "auto"][:left]
    manual = [x for x in todo if x["apply_mode"] != "auto"]
    log(f"{len(auto)} auto-apply jobs above score {prefs['min_score']}, {len(manual)} need manual apply")
    if auto:
        apply_batch(auto, uid, bool(prefs.get("auto_submit") or config.AUTO_SUBMIT))
    if manual:
        notify.notify("Manual applications waiting", f"{len(manual)} good-fit jobs are on external sites.", urgent=False)
