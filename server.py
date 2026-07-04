"""
N.E.X.U.S — Project Hermes Relay Server V2
RAILWAY DEPLOYMENT

Extends the existing mobile bridge with:
  /feed          — Founder Feed (real-time activity timeline)
  /sync          — Full data sync blob (projects, stark, atlas, health)
  /notify        — Smart notifications
  /phone/command — Remote command execution with live progress

All EXISTING endpoints are UNCHANGED:
  /phone/send, /phone/poll, /desktop/pull, /desktop/respond
"""

import os
import json
import time
import secrets
import hashlib
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="N.E.X.U.S Hermes Relay")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# ── AUTH ──────────────────────────────────────────────────────────────────
PASSCODE      = os.environ.get("NEXUS_MOBILE_PASSCODE", "")
if not PASSCODE:
    PASSCODE  = secrets.token_hex(4)
    print(f"[WARNING] NEXUS_MOBILE_PASSCODE not set — random: {PASSCODE}")

PASSCODE_HASH = hashlib.sha256(PASSCODE.encode()).hexdigest()


def _auth(x_nexus_passcode: str = ""):
    if not secrets.compare_digest(
            hashlib.sha256(x_nexus_passcode.encode()).hexdigest(),
            PASSCODE_HASH):
        raise HTTPException(status_code=401, detail="Invalid passcode")


# ── IN-MEMORY STATE ───────────────────────────────────────────────────────
_to_desktop:        list  = []   # phone→desktop queue
_to_phone:          list  = []   # desktop→phone response queue
_last_desktop_poll: float = 0.0

# Hermes state
_feed:              list  = []   # Founder Feed events (max 500)
_sync_blob:         dict  = {}   # latest data sync from PC
_notifications:     list  = []   # unread notifications (max 100)
_command_results:   dict  = {}   # {command_id: {status, progress, result}}


# ── PYDANTIC MODELS ───────────────────────────────────────────────────────
class PhoneMessage(BaseModel):
    text: str

class DesktopResponse(BaseModel):
    request_id: str
    text: str

class FeedEvent(BaseModel):
    subsystem:  str
    event_type: str           # "artifact"|"milestone"|"alert"|"stark"|"darwin"
    title:      str
    detail:     str = ""
    project:    str = ""
    icon:       str = "✓"
    priority:   str = "normal"  # "normal"|"high"|"critical"
    artifact_path: str = ""

class SyncData(BaseModel):
    data: dict

class Notification(BaseModel):
    title:    str
    body:     str
    priority: str = "normal"
    action:   str = ""         # deep link action e.g. "open_stark"

class CommandRequest(BaseModel):
    command:  str
    source:   str = "phone"

class CommandUpdate(BaseModel):
    command_id: str
    status:     str            # "running"|"complete"|"error"
    progress:   str = ""
    result:     str = ""


# ── HELPER ────────────────────────────────────────────────────────────────
def _ts() -> str:
    return datetime.utcnow().isoformat()

def _now_display() -> str:
    from datetime import timezone
    return datetime.now().strftime("%H:%M")


# ── EXISTING ENDPOINTS (UNCHANGED) ────────────────────────────────────────

@app.get("/health")
def health():
    desktop_live = (time.time() - _last_desktop_poll) < 120
    return {
        "status":           "online",
        "desktop_connected": desktop_live,
        "feed_events":      len(_feed),
        "unread_notifs":    len([n for n in _notifications if not n.get("read")]),
        "version":          "hermes_v2",
    }


@app.post("/phone/send")
def phone_send(msg: PhoneMessage,
               x_nexus_passcode: str = Header(default="")):
    _auth(x_nexus_passcode)
    request_id = secrets.token_hex(6)
    _to_desktop.append({
        "request_id": request_id,
        "text":       msg.text,
        "queued_at":  _ts(),
        "source":     "phone",
    })
    return {"request_id": request_id, "queued": True}


@app.get("/phone/poll/{request_id}")
def phone_poll(request_id: str,
               x_nexus_passcode: str = Header(default="")):
    _auth(x_nexus_passcode)
    for i, resp in enumerate(_to_phone):
        if resp["request_id"] == request_id:
            _to_phone.pop(i)
            return {"ready": True, "text": resp["text"]}
    return {"ready": False}


@app.get("/desktop/pull")
def desktop_pull(x_nexus_passcode: str = Header(default="")):
    global _last_desktop_poll
    _auth(x_nexus_passcode)
    _last_desktop_poll = time.time()
    pending = list(_to_desktop)
    _to_desktop.clear()
    return {"messages": pending}


@app.post("/desktop/respond")
def desktop_respond(resp: DesktopResponse,
                    x_nexus_passcode: str = Header(default="")):
    _auth(x_nexus_passcode)
    _to_phone.append({
        "request_id": resp.request_id,
        "text":       resp.text,
        "at":         _ts(),
    })
    return {"delivered": True}


# ── FOUNDER FEED ──────────────────────────────────────────────────────────

@app.post("/feed/event")
def post_feed_event(event: FeedEvent,
                    x_nexus_passcode: str = Header(default="")):
    """PC posts events here. Shows in Founder Feed on phone."""
    _auth(x_nexus_passcode)
    entry = {
        "id":            secrets.token_hex(4),
        "time":          _now_display(),
        "timestamp":     _ts(),
        "subsystem":     event.subsystem,
        "event_type":    event.event_type,
        "title":         event.title,
        "detail":        event.detail,
        "project":       event.project,
        "icon":          event.icon,
        "priority":      event.priority,
        "artifact_path": event.artifact_path,
        "read":          False,
    }
    _feed.append(entry)
    if len(_feed) > 500:
        _feed.pop(0)

    # High priority events also generate a notification
    if event.priority in ("high","critical"):
        _notifications.append({
            "id":       entry["id"],
            "title":    event.title,
            "body":     event.detail[:100],
            "priority": event.priority,
            "at":       _ts(),
            "read":     False,
        })
        if len(_notifications) > 100:
            _notifications.pop(0)

    return {"posted": True, "id": entry["id"]}


@app.get("/feed")
def get_feed(limit: int = 50,
             x_nexus_passcode: str = Header(default="")):
    """Phone fetches the Founder Feed."""
    _auth(x_nexus_passcode)
    return {
        "events":   list(reversed(_feed[-limit:])),
        "total":    len(_feed),
        "unread":   len([e for e in _feed if not e.get("read")]),
    }


@app.post("/feed/mark_read")
def mark_feed_read(x_nexus_passcode: str = Header(default="")):
    _auth(x_nexus_passcode)
    for e in _feed:
        e["read"] = True
    return {"marked": len(_feed)}


# ── DATA SYNC ─────────────────────────────────────────────────────────────

@app.post("/sync/push")
def sync_push(data: SyncData,
              x_nexus_passcode: str = Header(default="")):
    """PC pushes its current state here every few minutes."""
    _auth(x_nexus_passcode)
    _sync_blob.update(data.data)
    _sync_blob["synced_at"] = _ts()
    return {"synced": True}


@app.get("/sync/pull")
def sync_pull(x_nexus_passcode: str = Header(default="")):
    """Phone pulls the latest PC state."""
    _auth(x_nexus_passcode)
    return _sync_blob if _sync_blob else {"synced_at": None, "offline": True}


# ── NOTIFICATIONS ─────────────────────────────────────────────────────────

@app.post("/notify")
def post_notification(notif: Notification,
                       x_nexus_passcode: str = Header(default="")):
    """PC sends a notification to the phone."""
    _auth(x_nexus_passcode)
    entry = {
        "id":       secrets.token_hex(4),
        "title":    notif.title,
        "body":     notif.body,
        "priority": notif.priority,
        "action":   notif.action,
        "at":       _ts(),
        "read":     False,
    }
    _notifications.append(entry)
    if len(_notifications) > 100:
        _notifications.pop(0)
    return {"sent": True}


@app.get("/notify/poll")
def poll_notifications(x_nexus_passcode: str = Header(default="")):
    """Phone polls for new notifications."""
    _auth(x_nexus_passcode)
    unread = [n for n in _notifications if not n.get("read")]
    # Mark as read after delivery
    for n in _notifications:
        n["read"] = True
    return {"notifications": unread, "count": len(unread)}


# ── REMOTE COMMANDS ───────────────────────────────────────────────────────

@app.post("/phone/command")
def phone_command(cmd: CommandRequest,
                  x_nexus_passcode: str = Header(default="")):
    """Phone sends a command, gets a command_id to track progress."""
    _auth(x_nexus_passcode)
    command_id = secrets.token_hex(6)
    # Queue as a regular desktop message with command tracking
    _to_desktop.append({
        "request_id": command_id,
        "text":       cmd.command,
        "queued_at":  _ts(),
        "source":     "phone_command",
    })
    _command_results[command_id] = {
        "status":   "queued",
        "progress": "Command received, sending to N.E.X.U.S...",
        "result":   "",
        "at":       _ts(),
    }
    return {"command_id": command_id, "queued": True}


@app.post("/desktop/command_update")
def command_update(update: CommandUpdate,
                   x_nexus_passcode: str = Header(default="")):
    """Desktop posts progress updates for long-running commands."""
    _auth(x_nexus_passcode)
    _command_results[update.command_id] = {
        "status":   update.status,
        "progress": update.progress,
        "result":   update.result,
        "at":       _ts(),
    }
    return {"updated": True}


@app.get("/phone/command/{command_id}")
def get_command_result(command_id: str,
                       x_nexus_passcode: str = Header(default="")):
    """Phone polls for command result."""
    _auth(x_nexus_passcode)
    result = _command_results.get(command_id)
    if not result:
        return {"status": "unknown"}
    # Clean up completed commands after delivery
    if result["status"] in ("complete","error"):
        _command_results.pop(command_id, None)
    return result


# ── PHONE APP (Hermes PWA) ─────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/app")


@app.get("/app", response_class=HTMLResponse)
def serve_app():
    """Serve the Hermes companion PWA."""
    here     = os.path.dirname(os.path.abspath(__file__))
    app_path = os.path.join(here, "hermes_app.html")
    try:
        with open(app_path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<h1>N.E.X.U.S Hermes</h1><p>App not found. Deploy hermes_app.html.</p>"
