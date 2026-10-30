"""SQLite storage. Every table carries user_id (default 1) so the same code
can serve many users when you later launch globally."""
import json
import sqlite3
import threading
from contextlib import contextmanager

from .config import DB_PATH

_lock = threading.Lock()
AUTO_ATS = ("greenhouse", "lever", "ashby", "naukri", "foundit", "shine", "internshala")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  profile TEXT DEFAULT '{}',
  prefs TEXT DEFAULT '{}',
  resume_path TEXT
);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER DEFAULT 1,
  source TEXT, ext_id TEXT, ats TEXT,
  title TEXT, company TEXT, location TEXT, url TEXT, description TEXT,
  work_mode TEXT, company_tier TEXT, company_type TEXT,
  score INTEGER DEFAULT 0, matched TEXT DEFAULT '[]', reason TEXT DEFAULT '',
  llm_scored INTEGER DEFAULT 0,
  status TEXT DEFAULT 'new', note TEXT DEFAULT '',
  applied_by TEXT DEFAULT '', apply_mode TEXT DEFAULT '',
  exp TEXT DEFAULT '', salary TEXT DEFAULT '',
  created TEXT DEFAULT CURRENT_TIMESTAMP, applied_at TEXT,
  UNIQUE(user_id, source, ext_id)
);
"""


@contextmanager
def _db():
    with _lock:
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def init():
    with _db() as c:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(jobs)")}
        for name in ("applied_by", "apply_mode", "exp", "salary"):  # upgrade older databases
            if name not in cols:
                c.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT DEFAULT ''")
        c.execute(
            "UPDATE jobs SET apply_mode=CASE WHEN ats IN ('greenhouse','lever','ashby','naukri','foundit','shine','internshala') THEN 'auto' ELSE 'manual' END "
            "WHERE apply_mode='' OR apply_mode IS NULL"
        )
        # a crash or a closed window can leave jobs stuck on "applying": put them back in the queue
        c.execute("UPDATE jobs SET status='new', note='Interrupted - ready to try again.' WHERE status='applying'")
        # foreign-only leftovers from the old version of JobPilot
        c.execute("DELETE FROM jobs WHERE source IN ('remotive','arbeitnow') AND status IN ('new','skipped')")
        c.execute("UPDATE jobs SET applied_by='ai' WHERE status='applied' AND (applied_by='' OR applied_by IS NULL)")


def clear_jobs(uid=1, statuses=("new", "skipped", "manual")):
    q = ",".join("?" * len(statuses))
    with _db() as c:
        return c.execute(f"DELETE FROM jobs WHERE user_id=? AND status IN ({q})", (uid, *statuses)).rowcount


def get_user(uid=1):
    with _db() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not r:
            c.execute("INSERT INTO users(id) VALUES(?)", (uid,))
            return {"id": uid, "profile": {}, "prefs": {}, "resume_path": None}
        return {
            "id": r["id"],
            "profile": json.loads(r["profile"] or "{}"),
            "prefs": json.loads(r["prefs"] or "{}"),
            "resume_path": r["resume_path"],
        }


def save_user(uid=1, profile=None, prefs=None, resume_path=None):
    get_user(uid)
    with _db() as c:
        if profile is not None:
            c.execute("UPDATE users SET profile=? WHERE id=?", (json.dumps(profile), uid))
        if prefs is not None:
            c.execute("UPDATE users SET prefs=? WHERE id=?", (json.dumps(prefs), uid))
        if resume_path is not None:
            c.execute("UPDATE users SET resume_path=? WHERE id=?", (str(resume_path), uid))


def add_job(uid, j):
    """Insert a job; return its id, or None if we already have it."""
    with _db() as c:
        cur = c.execute(
            """INSERT OR IGNORE INTO jobs
               (user_id,source,ext_id,ats,title,company,location,url,description,
                work_mode,company_tier,company_type,score,matched,reason,status,apply_mode,exp,salary)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                uid, j["source"], str(j["ext_id"]), j.get("ats", ""), j["title"], j["company"],
                j.get("location", ""), j["url"], (j.get("description") or "")[:20000],
                j.get("work_mode", ""), j.get("company_tier", ""), j.get("company_type", ""),
                j.get("score", 0), json.dumps(j.get("matched", [])), j.get("reason", ""), "new",
                "auto" if j.get("ats") in AUTO_ATS else "manual", j.get("exp", ""), j.get("salary", ""),
            ),
        )
        return cur.lastrowid if cur.rowcount else None


def _row(r):
    d = dict(r)
    d["matched"] = json.loads(d.get("matched") or "[]")
    return d


def jobs(uid=1, status=None, limit=500):
    q, args = "SELECT * FROM jobs WHERE user_id=?", [uid]
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY score DESC, id DESC LIMIT ?"
    args.append(limit)
    with _db() as c:
        return [_row(r) for r in c.execute(q, args).fetchall()]


def get_job(jid):
    with _db() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return _row(r) if r else None


def set_job(jid, **fields):
    if not fields:
        return
    if "matched" in fields:
        fields["matched"] = json.dumps(fields["matched"])
    cols = ", ".join(f"{k}=?" for k in fields)
    with _db() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", [*fields.values(), jid])


def applied_today(uid=1):
    with _db() as c:
        return c.execute(
            "SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('applied','ready') "
            "AND date(applied_at)=date('now')",
            (uid,),
        ).fetchone()[0]


def stats(uid=1):
    with _db() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) n FROM jobs WHERE user_id=? GROUP BY status", (uid,)
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}
