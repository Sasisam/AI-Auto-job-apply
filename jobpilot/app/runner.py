"""One background task at a time, with a real STOP button.

Everything long-running (search, auto-apply, portal login) runs through Runner.
Code inside a task calls runner.check() / runner.sleep() often; when you press Stop
those raise Stopped, the task unwinds, the browser closes and nothing is left half-done.
"""
import threading
import time
from collections import deque
from datetime import datetime


class Stopped(Exception):
    pass


class Runner:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.done_event = threading.Event()      # "I finished logging in" signal
        self.running = False
        self.phase = ""
        self.label = ""
        self.done = 0
        self.total = 0
        self.current = ""
        self.last_run = None
        self.last_summary = ""
        self.log_lines = deque(maxlen=400)
        self.counts = {}

    # ---- logging -------------------------------------------------------
    def log(self, msg):
        line = f"{datetime.now():%H:%M:%S}  {msg}"
        print(line, flush=True)
        self.log_lines.append(line)

    # ---- stop support --------------------------------------------------
    @property
    def stopping(self):
        return self.running and self.stop_event.is_set()

    def request_stop(self):
        if self.running:
            self.stop_event.set()
            self.done_event.set()
            self.log("STOP requested - finishing the current step and halting...")
            return True
        return False

    def check(self):
        if self.stop_event.is_set():
            raise Stopped()

    def sleep(self, seconds):
        """Interruptible sleep: wakes within 0.25s of a stop request."""
        end = time.time() + seconds
        while time.time() < end:
            self.check()
            time.sleep(min(0.25, max(0, end - time.time())))
        self.check()

    def wait_page(self, page, ms):
        """Playwright wait that can be interrupted by Stop."""
        end = time.time() + ms / 1000
        while time.time() < end:
            self.check()
            page.wait_for_timeout(int(min(400, max(50, (end - time.time()) * 1000))))
        self.check()

    # ---- progress ------------------------------------------------------
    def progress(self, done=None, total=None, current=None):
        if done is not None:
            self.done = done
        if total is not None:
            self.total = total
        if current is not None:
            self.current = current

    def count(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1

    # ---- start ---------------------------------------------------------
    def start(self, phase, fn, *args, label=""):
        """Start fn(*args) in a thread. Returns False if something is already running."""
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.phase, self.label = phase, label or phase
            self.done = self.total = 0
            self.current = ""
            self.counts = {}
            self.stop_event.clear()
            self.done_event.clear()
        threading.Thread(target=self._run, args=(fn, args), daemon=True).start()
        return True

    def _run(self, fn, args):
        stopped = False
        try:
            fn(*args)
        except Stopped:
            stopped = True
        except Exception as e:  # never let a crash leave the dashboard stuck
            msg = str(e).strip().splitlines()[0][:220] if str(e).strip() else type(e).__name__
            if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
                msg = "Browser engine missing. Run:  playwright install chromium"
            elif "without having a XServer" in str(e):
                msg = "No screen available for the browser window (set PORTAL_HEADLESS=true in .env)"
            self.log(f"ERROR: {msg}")
        finally:
            if stopped:
                self.log("Stopped. Nothing is running now.")
                self.last_summary = "Stopped by you."
            self.last_run = datetime.now().strftime("%d %b, %H:%M")
            with self.lock:
                self.running = False
                self.phase = self.label = self.current = ""
            self.stop_event.clear()


RUN = Runner()
log = RUN.log
