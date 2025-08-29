import os
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .db import get_connection, migrate, seed_example_data_if_empty
from .inbox import list_notifications as inbox_list, get_notification as inbox_get, mark_read as inbox_mark_read, unread_count as inbox_unread


app = FastAPI(title="Fantasy Bot")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


@app.on_event("startup")
def on_startup() -> None:
    migrate()
    seed_example_data_if_empty()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/")
def list_notifications(request: Request, kind: Optional[str] = None):
    rows = inbox_list(kind)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "notifications": rows,
            "unread": inbox_unread(),
            "filter_kind": kind or "",
        },
    )


@app.get("/notifications/{notification_id}")
def notification_detail(request: Request, notification_id: int):
    row = inbox_get(notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return templates.TemplateResponse(
        "detail.html", {"request": request, "n": row, "unread": inbox_unread()}
    )


@app.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int):
    inbox_mark_read(notification_id)
    return RedirectResponse(url=f"/notifications/{notification_id}", status_code=status.HTTP_303_SEE_OTHER)


