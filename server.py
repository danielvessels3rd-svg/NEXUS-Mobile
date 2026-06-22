"""
N.E.X.U.S V6.2 — Mobile Bridge (Stage A)
RAILWAY RELAY SERVER
"""

import os
import json
import time
import secrets
import hashlib
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

app = FastAPI(title="N.E.X.U.S Mobile Relay")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── AUTH ──────────────────────────────────────────────────────
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


# ── QUEUES ──────────────────────────────────────────────────────
_to_desktop: list = []
_to_phone: list = []
_last_desktop_poll: float = 0.0


class PhoneMessage(BaseModel):
    text: str


class DesktopResponse(BaseModel):
    request_id: str
    text: str


# ── ENDPOINTS ─────────────────────────────────────────────────

@app.get("/")
def root():
    """Redirect to the mobile app interface."""
    return RedirectResponse(url="/app")


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
    """Phone polls this to check if a response is ready."""
    _check_auth(x_nexus_passcode)
    for i, resp in enumerate(_to_phone):
        if resp["request_id"] == request_id:
            _to_phone.pop(i)
            return {"ready": True, "text": resp["text"]}
    return {"ready": False}


@app.get("/desktop/pull")
def desktop_pull(x_nexus_passcode: str = Header(default="")):
    """Desktop polls this to pick up queued phone messages."""
    global _last_desktop_poll
    _check_auth(x_nexus_passcode)
    _last_desktop_poll = time.time()
    pending = list(_to_desktop)
    _to_desktop.clear()
    return {"messages": pending}


@app.post("/desktop/respond")
def desktop_respond(resp: DesktopResponse, x_nexus_passcode: str = Header(default="")):
    """Desktop posts the real response after running handle_command()."""
    _check_auth(x_nexus_passcode)
    _to_phone.append({
        "request_id": resp.request_id,
        "text": resp.text,
    })
    return {"delivered": True}


@app.get("/app", response_class=HTMLResponse)
def serve_app():
    """Serves the mobile web app."""
    here = os.path.dirname(os.path.abspath(__file__))
    app_path = os.path.join(here, "mobile_app.html")
    try:
        with open(app_path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<h1>N.E.X.U.S Mobile</h1><p>App file not found.</p>"

