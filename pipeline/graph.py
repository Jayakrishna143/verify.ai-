"""pipeline/graph.py -- LangGraph StateGraph: retrieve -> plan -> tools -> fmt_node.

Node order
----------
1. retrieve   Pull relevant chunks from retrieval.search().
2. plan       LLM with tool binding writes a numbered plan. If ambiguous,
              interrupt() pauses the graph and asks for clarification.
3. tools      Execute tools called during plan/execution rounds until done.
4. fmt_node   Build the citation trace and render the answer text.

Checkpointer: MemorySaver (in-process) so interrupt()/resume works.
"""

import json
import logging
from typing import TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt, Command
from pydantic import BaseModel, Field

from pipeline import config as cfg
from pipeline import format as fmt
from pipeline.session import Session, TerminalSession
from retrieval import search as ret_search
from tools import metrics as met

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: extract text from response.content (supports str, list of dicts/parts)
# ---------------------------------------------------------------------------

def _extract_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
            elif hasattr(part, "text"):
                parts.append(part.text)
        return "".join(parts).strip()
    return str(content).strip()


# ---------------------------------------------------------------------------
# State -- TypedDict required by LangGraph
# ---------------------------------------------------------------------------

class PipelineState(TypedDict, total=False):
    question: str
    chunks: list
    plan: str
    tool_results: list
    answer: dict
    messages: list


def _initial_state(question: str) -> PipelineState:
    return PipelineState(
        question=question,
        chunks=[],
        plan="",
        tool_results=[],
        answer={},
        messages=[],
    )


# ---------------------------------------------------------------------------
# Build LangChain tools from tools.metrics
# ---------------------------------------------------------------------------

class _MetricArgs(BaseModel):
    ticker: str = Field(..., description="Company ticker, e.g. JPM.")
    fiscal_year: int = Field(..., description="Fiscal year, e.g. 2025.")


def _make_lc_tools() -> list[StructuredTool]:
    tools = []
    for spec in met.tool_specs():
        name = spec["name"]
        fn = met.REGISTRY[name]

        def _make_runner(bound_fn, bound_name):
            def _run(ticker: str, fiscal_year: int) -> dict:
                return bound_fn(ticker=ticker, fiscal_year=fiscal_year)
            _run.__name__ = bound_name
            return _run

        runner = _make_runner(fn, name)

        lct = StructuredTool(
            name=name,
            description=spec["description"],
            args_schema=_MetricArgs,
            func=runner,
        )
        tools.append(lct)
    return tools


_LC_TOOLS = _make_lc_tools()
_TOOL_MAP = {t.name: t for t in _LC_TOOLS}


# ---------------------------------------------------------------------------
# Node: retrieve
# ---------------------------------------------------------------------------

def node_retrieve(state: PipelineState) -> PipelineState:
    question = state["question"]
    log.info("retrieve: searching for %r", question)
    chunks = ret_search.search(question, limit=cfg.RETRIEVAL_LIMIT)
    log.info("retrieve: %d chunks", len(chunks))
    return {**state, "chunks": chunks}


# ---------------------------------------------------------------------------
# Node: plan (+ ambiguity interrupt)
# ---------------------------------------------------------------------------

def _chunks_context(chunks: list) -> str:
    if not chunks:
        return "(no retrieval context)"
    parts = []
    for c in chunks[:5]:
        doc = c.get("doc_id") or "?"
        sec = c.get("section_id") or "?"
        text = (c.get("text") or "")[:400]
        parts.append("[" + doc + " / " + sec + "]\n" + text)
    return "\n\n".join(parts)


def node_plan(state: PipelineState) -> PipelineState:
    """LLM writes a plan with tools bound. If ambiguous, interrupt()."""
    llm = cfg.get_llm()
    llm_with_tools = llm.bind_tools(_LC_TOOLS)
    context = _chunks_context(state.get("chunks", []))
    question = state["question"]

    messages = [
        SystemMessage(content=cfg.SYSTEM_PROMPT),
        HumanMessage(content="Context from filings:\n" + context + "\n\nQuestion: " + question),
    ]

    log.info("plan: invoking LLM for %r", question)
    response: AIMessage = llm_with_tools.invoke(messages)
    plan_text = _extract_text(response.content)
    tool_calls = getattr(response, "tool_calls", None) or []
    log.info("plan output (first 200): %s", plan_text[:200])

    # Ambiguity check: no tool calls AND text ends with "?" -> interrupt
    if not tool_calls and plan_text.endswith("?"):
        log.info("plan: ambiguous -- calling interrupt()")
        clarification = interrupt({"question": plan_text})
        messages.append(AIMessage(content=plan_text))
        messages.append(HumanMessage(content=str(clarification)))
        response2: AIMessage = llm_with_tools.invoke(messages)
        plan_text = _extract_text(response2.content)
        tool_calls = getattr(response2, "tool_calls", None) or []
        log.info("plan after clarification: %s", plan_text[:200])
        messages.append(response2)
    else:
        messages.append(response)

    return {**state, "plan": plan_text, "messages": messages}


# ---------------------------------------------------------------------------
# Node: tools
# ---------------------------------------------------------------------------

def node_tools(state: PipelineState) -> PipelineState:
    """Execute any tool calls in response and loop until no more calls."""
    llm = cfg.get_llm()
    llm_with_tools = llm.bind_tools(_LC_TOOLS)
    llm_forced = llm.bind_tools(_LC_TOOLS, tool_choice="any")

    messages = list(state.get("messages", []))
    tool_results = list(state.get("tool_results", []))
    max_rounds = 5

    # If the last message in state has no tool calls (e.g. model output plan text only),
    # force tool_choice="any" to execute the first planned tool call.
    last_msg = messages[-1] if messages else None
    if not (getattr(last_msg, "tool_calls", None) or []):
        log.info("tools: plan was text-only -- forcing tool execution")
        response: AIMessage = llm_forced.invoke(messages)
        messages.append(response)

    for round_num in range(max_rounds):
        last_msg = messages[-1] if messages else None
        tool_calls = getattr(last_msg, "tool_calls", None) or []

        if not tool_calls:
            log.info("tools: no more pending tool calls after round %d", round_num)
            break

        # Execute each pending tool call
        for tc in tool_calls:
            name = tc["name"]
            args = tc["args"]
            tool_call_id = tc["id"]
            log.info("tools: executing %s(%s)", name, args)

            lct = _TOOL_MAP.get(name)
            if lct is None:
                result = {"is_error": True, "error": "unknown tool " + repr(name)}
            else:
                try:
                    result = lct.invoke(args)
                except Exception as exc:
                    log.exception("tools: %s raised %s", name, exc)
                    result = {"is_error": True, "error": str(exc)}

            tool_results.append(result)
            messages.append(ToolMessage(
                content=json.dumps(result),
                tool_call_id=tool_call_id,
            ))

        # Ask LLM if further tool calls or finalization needed (auto mode allows stopping)
        log.info("tools: round %d, invoking LLM with tool results", round_num + 1)
        response: AIMessage = llm_with_tools.invoke(messages)
        messages.append(response)

    return {**state, "tool_results": tool_results, "messages": messages}


# ---------------------------------------------------------------------------
# Node: format
# ---------------------------------------------------------------------------

def node_format(state: PipelineState) -> PipelineState:
    payload = fmt.format_answer(
        question=state["question"],
        plan=state.get("plan", ""),
        tool_results=state.get("tool_results", []),
        chunks=state.get("chunks", []),
    )
    errors = fmt.validate_citations(payload)
    if errors:
        log.warning("citation validation: %d issue(s): %s", len(errors), errors)
    else:
        log.info("citation validation: all numbers have sources")
    return {**state, "answer": payload}


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_graph():
    """Compile the LangGraph pipeline with MemorySaver checkpointer."""
    g = StateGraph(PipelineState)
    g.add_node("retrieve", node_retrieve)
    g.add_node("plan", node_plan)
    g.add_node("tools", node_tools)
    g.add_node("fmt_node", node_format)

    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "plan")
    g.add_edge("plan", "tools")
    g.add_edge("tools", "fmt_node")
    g.add_edge("fmt_node", END)

    checkpointer = MemorySaver()
    return g.compile(checkpointer=checkpointer)


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ---------------------------------------------------------------------------
# High-level runner (called from run.py)
# ---------------------------------------------------------------------------

def run_question(question: str, session: Session | None = None,
                 thread_id: str = cfg.DEFAULT_THREAD_ID,
                 callbacks: list | None = None) -> dict:
    """Run one question end-to-end. Handle interrupt/resume for ambiguity."""
    if session is None:
        session = TerminalSession()

    graph = get_graph()
    thread_config = {"configurable": {"thread_id": thread_id}}
    if callbacks:
        thread_config["callbacks"] = callbacks

    initial = _initial_state(question)
    log.info("run_question: %r (thread=%s)", question, thread_id)

    result = graph.invoke(initial, config=thread_config)

    # Handle interrupt loop (ambiguity escalation)
    while True:
        snapshot = graph.get_state(thread_config)
        if not snapshot.next:
            break

        all_interrupts = []
        for task in (snapshot.tasks or []):
            all_interrupts.extend(getattr(task, "interrupts", []))

        if all_interrupts:
            interrupt_payload = all_interrupts[0].value
            question_text = interrupt_payload.get("question", "Please clarify.")
            user_answer = session.ask(question_text)
            result = graph.invoke(Command(resume=user_answer), config=thread_config)
        else:
            break

    final = graph.get_state(thread_config).values
    return final.get("answer", {})


def resume_question(thread_id: str, user_answer: str,
                    callbacks: list | None = None) -> dict:
    """Resume a graph paused at a clarification interrupt."""
    graph = get_graph()
    thread_config = {"configurable": {"thread_id": thread_id}}
    if callbacks:
        thread_config["callbacks"] = callbacks

    graph.invoke(Command(resume=user_answer), config=thread_config)

    while True:
        snapshot = graph.get_state(thread_config)
        if not snapshot.next:
            break
        all_interrupts = []
        for task in (snapshot.tasks or []):
            all_interrupts.extend(getattr(task, "interrupts", []))
        if all_interrupts:
            interrupt_payload = all_interrupts[0].value
            raise RuntimeError(
                f"Nested interrupt after resume: {interrupt_payload}"
            )
        break

    return graph.get_state(thread_config).values.get("answer", {})
