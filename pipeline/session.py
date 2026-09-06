"""pipeline/session.py — I/O abstraction for the interactive loop.

The graph never calls input() directly. It calls session.ask(question).
Swapping TerminalSession for a WebSession or an API callback requires no
change to graph.py -- just pass a different Session instance.
"""

import abc
import logging

log = logging.getLogger(__name__)


class Session(abc.ABC):
    """Abstract I/O channel between the graph and the user."""

    @abc.abstractmethod
    def ask(self, question: str) -> str:
        """Present question to the user; return their answer."""


class TerminalSession(Session):
    """Interactive terminal: print the question, read a line from stdin."""

    def ask(self, question: str) -> str:
        print()
        print("CLARIFICATION NEEDED")
        print("-" * 60)
        print(question)
        print("-" * 60)
        answer = input("Your answer: ").strip()
        log.info("user clarification: %r -> %r", question, answer)
        return answer


class ScriptedSession(Session):
    """Non-interactive session for tests: answers come from a pre-set list."""

    def __init__(self, answers: list[str]):
        self._answers = list(answers)

    def ask(self, question: str) -> str:
        if not self._answers:
            raise RuntimeError(f"ScriptedSession has no answer for: {question}")
        answer = self._answers.pop(0)
        log.info("scripted clarification: %r -> %r", question, answer)
        return answer
