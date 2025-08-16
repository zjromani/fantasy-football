import os
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .db import get_connection, migrate, seed_example_data_if_empty


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
    connection = get_connection()
    try:
        cursor = connection.cursor()
        if kind:
            cursor.execute(
                "SELECT * FROM notifications WHERE kind = ? ORDER BY is_read ASC, created_at DESC",
                (kind,),
            )
        else:
            cursor.execute(
                "SELECT * FROM notifications ORDER BY is_read ASC, created_at DESC"
            )
        rows = cursor.fetchall()

        cursor.execute(
            "SELECT COUNT(1) AS unread FROM notifications WHERE is_read = 0"
        )
        unread = cursor.fetchone()[0]

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "notifications": rows,
                "unread": unread,
                "filter_kind": kind or "",
            },
        )
    finally:
        connection.close()


@app.get("/notifications/{notification_id}")
def notification_detail(request: Request, notification_id: int):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (notification_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Notification not found")

        cursor.execute(
            "SELECT COUNT(1) AS unread FROM notifications WHERE is_read = 0"
        )
        unread = cursor.fetchone()[0]

        return templates.TemplateResponse(
            "detail.html", {"request": request, "n": row, "unread": unread}
        )
    finally:
        connection.close()


@app.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ?",
            (notification_id,),
        )
        connection.commit()
    finally:
        connection.close()
    return RedirectResponse(url=f"/notifications/{notification_id}", status_code=status.HTTP_303_SEE_OTHER)


