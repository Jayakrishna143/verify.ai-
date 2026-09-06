"""api/main.py — FastAPI backend for verify_ai chat."""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import api.db as db
from api.runner import get_status, start_run, start_resume


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="verify-ai", lifespan=lifespan)

_HTML = Path(__file__).parent.parent / "frontend" / "index.html"


@app.get("/", response_class=HTMLResponse)
def ui():
    return _HTML.read_text()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class MessageRequest(BaseModel):
    content: str


@app.post("/conversations")
def create_conversation():
    return db.create_conversation(title="New conversation")


@app.get("/conversations")
def list_conversations():
    return db.list_conversations()


@app.get("/conversations/{cid}/messages")
def get_messages(cid: str):
    conv = db.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return db.list_messages(cid)


@app.post("/conversations/{cid}/messages")
def post_message(cid: str, req: MessageRequest):
    conv = db.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    content = req.content.strip()
    if not content:
        raise HTTPException(400, "Empty message")

    if conv["status"] == "awaiting_clarification":
        request_id = start_resume(cid, content, cid)
    else:
        db.add_message(cid, "user", content, message_type="answer")
        if conv["title"] == "New conversation":
            title = content[:60] + ("..." if len(content) > 60 else "")
            db.set_conversation_title(cid, title)
        request_id = start_run(cid, content, cid)

    return {"request_id": request_id}


@app.delete("/conversations/{cid}")
def delete_conversation(cid: str):
    if not db.get_conversation(cid):
        raise HTTPException(404, "Conversation not found")
    db.delete_conversation(cid)
    return {"ok": True}


@app.get("/requests/{request_id}")
def poll_request(request_id: str):
    status = get_status(request_id)
    if status is None:
        raise HTTPException(404, "Request not found")
    return status
