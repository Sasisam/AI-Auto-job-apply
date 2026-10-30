import os
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, filters, llm, matcher, notify, pipeline, portals, resume
from .runner import RUN

STATIC = Path(__file__).resolve().parent.parent / "static"
UID = 1  # single user today; the schema is already multi-user
db.init()


def _scheduler():
    while config.RUN_EVERY_MINUTES > 0:
        time.sleep(config.RUN_EVERY_MINUTES * 60)
        RUN.start("auto-run", pipeline.run_once, UID, label="Scheduled run")


@asynccontextmanager
async def lifespan(_app):
    if config.RUN_EVERY_MINUTES > 0:
        threading.Thread(target=_scheduler, daemon=True).start()
    if config.OPEN_BROWSER:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{config.PORT}")).start()
    yield


app = FastAPI(title="JobPilot", lifespan=lifespan)
app.mount("/shots", StaticFiles(directory=str(config.SHOTS)), name="shots")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def _resume_info(user):
    p = resume.active_path(user["resume_path"])
    if not p:
        return None
    st = p.stat()
    return {"name": p.name, "kb": round(st.st_size / 1024), "modified": datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y, %H:%M"),
            "folder": str(config.RESUME_DIR), "ext": p.suffix.lower().lstrip(".")}


def _start(phase, fn, *args, label=""):
    return {"started": RUN.start(phase, fn, *args, label=label)}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def state():
    u = db.get_user(UID)
    return {
        "profile": u["profile"],
        "prefs": pipeline.effective_prefs(u["prefs"]),
        "resume": _resume_info(u),
        "ai_enabled": llm.available(),
        "email_enabled": bool(config.SMTP_USER and config.SMTP_PASS),
        "push_enabled": bool(config.NTFY_TOPIC),
        "portals": [
            {"id": p.id, "name": p.name, "auto": p.auto, "blurb": p.blurb, "connected": config.portal_connected(p.id)}
            for p in portals.PORTALS.values()
        ],
        "city_presets": filters.CITY_PRESETS,
        "run": {
            "running": RUN.running, "stopping": RUN.stopping, "phase": RUN.phase, "label": RUN.label,
            "done": RUN.done, "total": RUN.total, "current": RUN.current,
            "last_run": RUN.last_run, "summary": RUN.last_summary,
        },
        "stats": db.stats(UID),
        "applied_today": db.applied_today(UID),
        "log": list(RUN.log_lines)[-80:],
    }


# ---------------------------------------------------------------- stop
@app.post("/api/stop")
def stop():
    """The STOP button: halts search / auto-apply / login within a second or two."""
    return {"stopping": RUN.request_stop()}


# ---------------------------------------------------------------- resume
@app.post("/api/resume")
async def upload_resume(file: UploadFile = File(...)):
    try:
        dest = resume.save_upload(file.file, file.filename or "resume.pdf")
    except ValueError as e:
        raise HTTPException(400, str(e))
    text = resume.extract_text(dest)
    if len(text.strip()) < 50:
        resume.remove_active()
        raise HTTPException(400, "Could not read text from this file (scanned image?). Use a text PDF or DOCX.")
    profile = resume.parse_profile(text)
    db.save_user(UID, profile=profile, resume_path=dest)
    return {"profile": profile, "resume": _resume_info(db.get_user(UID))}


@app.post("/api/resume/rescan")
def rescan_resume():
    """Use the file you dropped into the resume folder by hand."""
    p = resume.active_path(None)
    if not p:
        raise HTTPException(404, "The resume folder is empty.")
    profile = resume.parse_profile(resume.extract_text(p))
    db.save_user(UID, profile=profile, resume_path=p)
    return {"profile": profile, "resume": _resume_info(db.get_user(UID))}


@app.get("/api/resume/file")
def resume_file():
    p = resume.active_path(db.get_user(UID)["resume_path"])
    if not p:
        raise HTTPException(404)
    return FileResponse(p, filename=p.name)


@app.delete("/api/resume")
def delete_resume():
    resume.remove_active()
    return {"ok": True}


@app.post("/api/resume/open-folder")
def open_folder():
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(config.RESUME_DIR))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(config.RESUME_DIR)])
        else:
            subprocess.Popen(["xdg-open", str(config.RESUME_DIR)])
    except Exception:
        pass
    return {"folder": str(config.RESUME_DIR)}


class Body(BaseModel):
    data: dict


@app.put("/api/profile")
def put_profile(b: Body):
    db.save_user(UID, profile=b.data)
    return {"ok": True}


@app.put("/api/prefs")
def put_prefs(b: Body):
    db.save_user(UID, prefs=b.data)
    return {"ok": True}


# ---------------------------------------------------------------- search + portals
class SearchBody(BaseModel):
    roles: List[str]
    locations: Optional[List[str]] = None
    work_modes: Optional[List[str]] = None
    company_tiers: Optional[List[str]] = None
    company_types: Optional[List[str]] = None
    portals: Optional[List[str]] = None
    experience_years: Optional[float] = None


@app.post("/api/search")
def search(b: SearchBody):
    roles = [r.strip() for r in b.roles if r.strip()]
    if not roles:
        raise HTTPException(400, "Add at least one role")
    u = db.get_user(UID)
    if not u["profile"]:
        raise HTTPException(400, "Upload your resume first")
    prefs = dict(u["prefs"])
    prefs["roles"] = roles
    for k in ("locations", "work_modes", "company_tiers", "company_types", "portals", "experience_years"):
        v = getattr(b, k)
        if v is not None:
            prefs[k] = v
    db.save_user(UID, prefs=prefs)
    return _start("search", pipeline.discover, UID, label="Searching jobs")


@app.post("/api/portals/{pid}/connect")
def portal_connect(pid: str):
    p = portals.PORTALS.get(pid)
    if not p or not p.auto:
        raise HTTPException(404, "This portal cannot be connected")
    return _start("login", portals.connect, pid, label=f"Log in to {p.name}")


@app.post("/api/portals/done")
def portal_done():
    """'I'm logged in' - lets the login window finish and checks the session."""
    RUN.done_event.set()
    return {"ok": True}


@app.post("/api/portals/{pid}/disconnect")
def portal_disconnect(pid: str):
    config.set_portal_connected(pid, False)
    return {"ok": True}


@app.get("/api/portals/links")
def portal_links(role: str = "", loc: str = ""):
    return [{"id": p.id, "name": p.name, "url": p.manual_url(role or "jobs", loc)} for p in portals.PORTALS.values() if p.manual_url]


# ---------------------------------------------------------------- jobs
@app.get("/api/jobs")
def list_jobs(status: str = "", roles: str = ""):
    rows = db.jobs(UID, status or None)
    wanted = [r.strip() for r in roles.split("|") if r.strip()]
    if wanted:
        rows = [j for j in rows if matcher.title_fit(wanted, j["title"]) >= 0.5]
    return rows


@app.post("/api/jobs/clear")
def clear_jobs():
    return {"removed": db.clear_jobs(UID)}


@app.post("/api/run")
def run_now():
    return _start("auto-run", pipeline.run_once, UID, label="Search + auto-apply")


class ApplyBody(BaseModel):
    ids: List[int]
    submit: bool = False


@app.post("/api/apply")
def apply_selected(b: ApplyBody):
    if not b.ids:
        raise HTTPException(400, "No jobs selected")
    if not resume.active_path(db.get_user(UID)["resume_path"]):
        raise HTTPException(400, "Upload your resume first. JobPilot applies with the file in your resume folder.")
    return _start("apply", pipeline.apply_batch, b.ids, UID, b.submit, label="Auto-applying")


@app.post("/api/jobs/{jid}/approve")
def approve(jid: int):
    if not db.get_job(jid):
        raise HTTPException(404)
    return _start("apply", pipeline.process_application, jid, UID, True, label="Submitting application")


@app.post("/api/jobs/{jid}/retry")
def retry(jid: int):
    if not db.get_job(jid):
        raise HTTPException(404)
    return _start("apply", pipeline.process_application, jid, UID, False, label="Retrying")


class StatusBody(BaseModel):
    status: str


@app.post("/api/jobs/{jid}/status")
def set_status(jid: int, b: StatusBody):
    if b.status not in ("new", "skipped", "applied", "manual"):
        raise HTTPException(400, "bad status")
    fields = {"status": b.status}
    if b.status == "applied":
        fields.update(applied_by="human", applied_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), note="Applied by you.")
    db.set_job(jid, **fields)
    return {"ok": True}


@app.post("/api/test-notify")
def test_notify():
    return {"sent": notify.notify("Test notification", "JobPilot can reach you here.")}
