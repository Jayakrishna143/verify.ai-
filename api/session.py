"""api/session.py — WebSession for non-interactive pipeline calls."""
from pipeline.session import Session


class ClarificationNeeded(Exception):
    def __init__(self, question: str):
        self.question = question


class WebSession(Session):
    """Raises ClarificationNeeded instead of blocking for user input."""

    def ask(self, question: str) -> str:
        raise ClarificationNeeded(question)
