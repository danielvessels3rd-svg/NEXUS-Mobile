"""
N.E.X.U.S V6.2 — Mobile Bridge (Stage A)
RAILWAY RELAY SERVER

This is the ONLY piece of N.E.X.U.S that runs on the public internet.
It is deliberately small, deliberately dumb, and deliberately unable
to do anything destructive -- it is a message relay, not a second
brain. Per the directive: "this is NOT a second personality, it is
the same N.E.X.U.S."

ARCHITECTURE, AND WHY IT'S SHAPED THIS WAY:
Your real N.E.X.U.S brain runs on your desktop at home. Railway
cannot reach into your home network (and I'm not asking you to open
port forwarding -- that's a real security exposure not worth taking
for this). So this server never executes anything itself. It only:

    1. Accepts a message from the phone, queues it.
    2. Lets the desktop (which POLLS this server periodically, same
       background-thread pattern already proven tonight in
       ImprovementObserver/WorkshopObserver) pick up queued messages.
    3. Accepts the REAL response from the desktop (after it actually
       ran the command through the real handle_command()), queues
       that for the phone to pick up.
    4. Never runs a command itself. Never touches a file. Never
       calls anything destructive. It is structurally incapable of
       being the thing that deletes memory or merges to production --
       those capabilities don't exist anywhere in this file.

AUTHENTICATION: a single shared passcode (set via Railway's own
environment variable system, never hardcoded in this file) gates
every endpoint. Per the directive's continuity-not-synchronization
principle, this is ONE shared secret between your phone and your
desktop -- not a multi-user system, not a public API.
"""

import os
import json
import time
import secrets
import hashlib
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="N.E.X.U.S Mobile Relay")

# CORS: allow the phone's browser to call this server. Restricting to
# any origin is acceptable here since the passcode is the real gate,
# not the browser's origin -- but kept narrow and documented.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── AUTH ──────────────────────────────────────────────────────
# Set via Railway's environment variables dashboard, NEVER committed
# to the repo. Falls back to a randomly generated value if unset so
# the server never silently runs with a blank/guessable passcode --
# if you see a random string in the logs on first boot, that means
# you forgot to set NEXUS_MOBILE_PASSCODE in Railway and should do so.
PASSCODE = os.environ.get("NEXUS_MOBILE_PASSCODE")
if not PASSCODE:
    PASSCODE = secrets.token_hex(4)
    print(f"[WARNING] NEXUS_MOBILE_PASSCODE not set -- using random "
          f"passcode for this boot only: {PASSCODE}")
    print("[WARNING] Set NEXUS_MOBILE_PASSCODE in Railway's environment "
          "variables for a stable passcode across restarts.")

PASSCODE_HASH = hashlib.sha256(PASSCODE.encode()).hexdigest()


def _check_auth(x_nexus_passcode: str = Header(default="")):
    provided_hash = hashlib.sha256(x_nexus_passcode.encode()).hexdigest()
    if not secrets.compare_digest(provided_hash, PASSCODE_HASH):
        raise HTTPException(status_code=401, detail="Invalid passcode")


# ── QUEUES (in-memory, deliberately ephemeral) ──────────────────
# Per directive: "failures should be honest... never fabricate
# continuity." If this server restarts, queued messages are
# genuinely gone -- this is documented and surfaced honestly to the
# desktop poller (queue_empty != error), never silently invented.

_to_desktop: list = []     # messages FROM phone, awaiting desktop pickup
_to_phone: list = []       # responses FROM desktop, awaiting phone pickup
_last_desktop_poll: float = 0.0


class PhoneMessage(BaseModel):
    text: str


class DesktopResponse(BaseModel):
    request_id: str
    text: str


# ── ENDPOINTS ─────────────────────────────────────────────────

@app.get("/")
def root():
    """Plain health check -- no auth required, reveals nothing sensitive."""
    return {"status": "online", "service": "N.E.X.U.S Mobile Relay"}


@app.get("/health")
def health():
    desktop_seen_recently = (time.time() - _last_desktop_poll) < 120
    return {
        "status": "online",
        "desktop_connected": desktop_seen_recently,
    }


@app.post("/phone/send")
def phone_send(msg: PhoneMessage, x_nexus_passcode: str = Header(default="")):
    """Phone calls this to send a message to N.E.X.U.S."""
    _check_auth(x_nexus_passcode)
    request_id = secrets.token_hex(6)
    _to_desktop.append({
        "request_id": request_id,
        "text": msg.text,
        "queued_at": datetime.utcnow().isoformat(),
    })
    return {"request_id": request_id, "queued": True}


@app.get("/phone/poll/{request_id}")
def phone_poll(request_id: str, x_nexus_passcode: str = Header(default="")):
    """
    Phone polls this to check if a response is ready yet. Honest
    'not ready' rather than fabricating a response.
    """
    _check_auth(x_nexus_passcode)
    for i, resp in enumerate(_to_phone):
        if resp["request_id"] == request_id:
            _to_phone.pop(i)
            return {"ready": True, "text": resp["text"]}
    return {"ready": False}


@app.get("/desktop/pull")
def desktop_pull(x_nexus_passcode: str = Header(default="")):
    """
    Desktop polls this periodically to pick up queued phone messages.
    Per directive's session-migration principle: this is the SAME
    polling pattern, reused for live chat instead of session state.
    """
    global _last_desktop_poll
    _check_auth(x_nexus_passcode)
    _last_desktop_poll = time.time()
    pending = list(_to_desktop)
    _to_desktop.clear()
    return {"messages": pending}


@app.post("/desktop/respond")
def desktop_respond(resp: DesktopResponse, x_nexus_passcode: str = Header(default="")):
    """
    Desktop calls this with the REAL response after actually running
    the command through the real handle_command(). This server never
    generates a response itself.
    """
    _check_auth(x_nexus_passcode)
    _to_phone.append({
        "request_id": resp.request_id,
        "text": resp.text,
    })
    return {"delivered": True}


@app.get("/app", response_class=HTMLResponse)
def serve_app():
    """Serves the mobile web app itself -- see mobile_app.html."""
    here = os.path.dirname(os.path.abspath(__file__))
    app_path = os.path.join(here, "mobile_app.html")
    try:
        with open(app_path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<h1>N.E.X.U.S Mobile</h1><p>App file not found.</p>"
