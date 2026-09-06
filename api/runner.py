"""api/runner.py — Run pipeline in a thread pool; track step status."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from langchain_core.callbacks import BaseCallbackHandler

from pipeline.graph import run_question, resume_question
from api.session import WebSession, ClarificationNeeded
import api.db as db

_pool = ThreadPoolExecutor(max_workers=4)

# In-memory status dict. Key: request_id.
# Value: {status, step, message, question}
# status values: "running" | "done" | "clarification" | "error"
_status: dict[str, dict] = {}

# Node name -> user-visible label. Names match the registered node names in graph.py.
NODE_LABELS = {
    "retrieve": "Retrieving relevant filings...",
    "plan":     "Planning the answer...",
    "tools":    "Computing metrics...",
    "fmt_node": "Formatting answer with citations...",
}


class StepTracker(BaseCallbackHandler):
    def __init__(self, request_id: str):
        self.request_id = request_id

    def on_chain_start(self, serialized, inputs, **kwargs):
        name = (serialized or {}).get("name", "")
        label = NODE_LABELS.get(name)
        if label and self.request_id in _status:
            _status[self.request_id]["step"] = label


def get_status(request_id: str) -> dict | None:
    return _status.get(request_id)


def start_run(conversation_id: str, question: str, thread_id: str) -> str:
    """Start a new pipeline run. Returns request_id immediately."""
    request_id = str(uuid.uuid4())
    _status[request_id] = {"status": "running", "step": "Starting..."}
    _pool.submit(_run, conversation_id, question, thread_id, request_id)
    return request_id


def start_resume(conversation_id: str, user_answer: str, thread_id: str) -> str:
    """Resume a paused pipeline after clarification. Returns request_id."""
    request_id = str(uuid.uuid4())
    _status[request_id] = {"status": "running", "step": "Resuming..."}
    _pool.submit(_resume, conversation_id, user_answer, thread_id, request_id)
    return request_id


def _run(conversation_id: str, question: str, thread_id: str, request_id: str):
    tracker = StepTracker(request_id)
    try:
        answer = run_question(
            question=question,
            session=WebSession(),
            thread_id=thread_id,
            callbacks=[tracker],
        )
        _finish(conversation_id, request_id, answer)
    except ClarificationNeeded as exc:
        db.add_message(conversation_id, "assistant", exc.question,
                       message_type="clarification_request")
        db.set_conversation_status(conversation_id, "awaiting_clarification")
        _status[request_id] = {"status": "clarification", "question": exc.question}
    except Exception as exc:
        _status[request_id] = {"status": "error", "message": str(exc)}


def _resume(conversation_id: str, user_answer: str, thread_id: str, request_id: str):
    tracker = StepTracker(request_id)
    db.add_message(conversation_id, "user", user_answer,
                   message_type="clarification_response")
    db.set_conversation_status(conversation_id, "active")
    try:
        answer = resume_question(
            thread_id=thread_id,
            user_answer=user_answer,
            callbacks=[tracker],
        )
        _finish(conversation_id, request_id, answer)
    except Exception as exc:
        _status[request_id] = {"status": "error", "message": str(exc)}


def _finish(conversation_id: str, request_id: str, answer: dict):
    answer_text = answer.get("answer_text", "")
    numbers = answer.get("numbers", [])
    metadata = {
        "numbers": numbers,
        "plan": answer.get("plan", ""),
        "chunks_used": answer.get("chunks_used", []),
    }
    msg = db.add_message(conversation_id, "assistant", answer_text,
                         message_type="answer", metadata=metadata)
    _status[request_id] = {"status": "done", "message": msg}
