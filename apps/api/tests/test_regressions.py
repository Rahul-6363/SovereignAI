"""Regression tests for bugs found in the code review.

Each test here pins a defect that was live in the codebase, so a refactor
cannot quietly reintroduce it.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO))

from fastapi.routing import APIRoute  # noqa: E402

from app.main import app  # noqa: E402
from app.services.answer_generator import _retrieval_query  # noqa: E402
from app.services.hybrid_retriever import HybridRetriever  # noqa: E402


# ── routing ───────────────────────────────────────────────────
def test_no_duplicate_route_registrations():
    """chat.py registered `project_conversations` and `get_conversation` twice;
    the shadowed copies were dead code that silently drifted out of sync."""
    seen: dict[tuple[str, str], int] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            key = (method, route.path)
            seen[key] = seen.get(key, 0) + 1
    duplicates = {k: v for k, v in seen.items() if v > 1}
    assert duplicates == {}, f"duplicate routes registered: {duplicates}"


# ── retrieval fusion ──────────────────────────────────────────
def test_rrf_emits_numeric_scores():
    """`_rrf_rank` unpacked items.items() and wrote the item dict into
    `score`, so every retrieval result carried a dict where a float belonged."""
    ranked = HybridRetriever._rrf_rank(
        [
            [{"source": "entity", "tag": "P-101"}, {"source": "entity", "tag": "V-2"}],
            [{"source": "graph", "tag": "P-101"}],
        ],
        top_k=5,
    )
    assert ranked, "expected fused results"
    for item in ranked:
        assert isinstance(item["score"], float), item
        assert isinstance(item["rank"], int)


def test_rrf_rewards_agreement_between_retrievers():
    """A hit returned by two retrievers must outrank one returned by one."""
    shared = {"source": "entity", "tag": "P-101"}
    solo = {"source": "entity", "tag": "V-2"}
    ranked = HybridRetriever._rrf_rank([[shared, solo], [shared]], top_k=5)
    assert ranked[0]["tag"] == "P-101"
    assert ranked[0]["score"] > ranked[1]["score"]


# ── multi-turn follow-ups ─────────────────────────────────────
def test_retrieval_query_carries_tag_from_prior_turn():
    """A bare follow-up has no tag of its own and used to retrieve nothing."""
    history = [
        {"role": "user", "content": "What instruments are connected to P-101?"},
        {"role": "assistant", "content": "PI-101 and TIC-102."},
    ]
    widened = _retrieval_query("and what is upstream of it?", history)
    assert "P-101" in widened
    assert "upstream" in widened


def test_retrieval_query_left_alone_when_self_contained():
    history = [{"role": "user", "content": "What is P-101?"}]
    assert _retrieval_query("Describe V-205", history) == "Describe V-205"
    assert _retrieval_query("What is P-101?", None) == "What is P-101?"


# ── evidence provenance ───────────────────────────────────────
def test_attach_document_meta_resolves_page_numbers():
    """`attach_document_meta` referenced `select` without importing it, so the
    NameError was swallowed and every source kept a raw page_id as its page."""
    from sqlmodel import Session

    from app.db import engine, init_db
    from app.models import Document, DocumentPage, Project
    from app.services.evidence_builder import attach_document_meta

    init_db()
    with Session(engine) as session:
        project = Project(name="regression-evidence")
        session.add(project)
        session.commit()
        session.refresh(project)

        doc = Document(project_id=project.id, name="sheet-3.pdf", status="ready")
        session.add(doc)
        session.commit()
        session.refresh(doc)

        # page_number 7 deliberately differs from the row's primary key.
        page = DocumentPage(document_id=doc.id, page_number=7, image_path="x.png")
        session.add(page)
        session.commit()
        session.refresh(page)

        packet = {
            "answer_context": [
                {"source_type": "pid", "entity": "P-101", "page": page.id}
            ]
        }
        out = attach_document_meta(session, packet)
        source = out["answer_context"][0]

        assert source["page"] == 7, "page_id was not translated to page_number"
        assert source["document_id"] == doc.id
        assert source["document"] == "sheet-3.pdf"

        # cleanup
        session.delete(page)
        session.delete(doc)
        session.delete(project)
        session.commit()


# ── conversation threads (multi-chat, persisted context) ──────
def test_conversation_crud_routes_exist():
    """The chat rail needs to create, rename, delete and list threads. Without
    these the UI can only ever append to one implicit conversation."""
    routes = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert ("POST", "/api/projects/{project_id}/conversations") in routes
    assert ("PATCH", "/api/conversations/{conversation_id}") in routes
    assert ("DELETE", "/api/conversations/{conversation_id}") in routes
    assert ("GET", "/api/conversations/{conversation_id}/messages") in routes


def test_messages_carry_back_evidence_and_artifacts():
    """A reopened thread must be identical to the live one. If the transcript
    returns text only, every citation stops resolving and every generated file
    becomes undownloadable."""
    from app.schemas import MessageOut

    fields = MessageOut.model_fields
    for name in ("sources", "claims", "artifacts", "kind"):
        assert name in fields, f"MessageOut lost {name}"


def test_streams_read_conversation_id_before_yielding():
    """The request session is closed by the time SSE events are produced.
    Touching `conv.id` inside the generator raised DetachedInstanceError
    mid-stream, which the client saw as a response that simply stopped."""
    import inspect

    from app.routers import chat, deliverables

    for func in (chat.chat_stream, deliverables.run_agent_task):
        source = inspect.getsource(func)
        body = source[source.index("async def gen("):]
        assert "conv.id" not in body, (
            f"{func.__name__} touches a detached ORM attribute while streaming"
        )
        assert "conversation_id" in body


def test_agent_turns_persist_into_the_thread():
    """An agent turn belongs to the same thread as the chat around it, or the
    conversation reads as though nothing answered and the file it made is lost
    on reload."""
    import inspect

    from app.routers import deliverables

    source = inspect.getsource(deliverables.run_agent_task)
    assert "_resolve_conversation" in source
    assert "_persist_agent_turn" in source
    assert "artifacts_json" in inspect.getsource(deliverables._persist_agent_turn)


# ── grounding: retrieval always returns something ─────────────
def test_unknown_tag_is_not_answered_from_a_neighbour_s_evidence():
    """Hybrid retrieval always returns its nearest neighbours, so a packet is
    never empty — asked about a tag that does not exist, the model answered
    using P-101's evidence, confidently, at confidence 0.94. Grounding has to
    mean the asked-about tag is actually present."""
    from app.services.answer_generator import _tags_present

    packet = {
        "answer_context": [
            {"entity": "P-101", "text": "Centrifugal Pump"},
            {"entity": "PI-102", "relation": "HAS_INSTRUMENT", "target": "P-101"},
        ]
    }
    assert _tags_present(packet, ["P-101"]) is True
    assert _tags_present(packet, ["PI-102"]) is True
    assert _tags_present(packet, ["XYZ-999"]) is False
    # No tag named means nothing to check against.
    assert _tags_present(packet, []) is True
    assert _tags_present({"answer_context": []}, ["P-101"]) is False


def test_model_prompt_drops_ui_only_fields():
    """bboxes and row ids exist so the UI can place a citation. Sending them
    to the model costs prompt tokens on every turn and buys nothing, which on
    CPU is seconds per question."""
    from app.services.context import render_evidence

    rendered = render_evidence(
        [{
            "source_type": "pid", "entity": "P-101", "text": "Centrifugal Pump",
            "document": "a.png", "page": 1,
            "bbox": [0.1, 0.2, 0.3, 0.4], "document_id": 11, "entity_id": 41,
            "confidence": 0.97,
        }],
        "what is P-101?",
        budget_tokens=400,
    )
    assert "P-101" in rendered
    assert "Centrifugal Pump" in rendered
    assert "a.png" in rendered and "p1" in rendered
    # The UI-only values must not appear anywhere in the prompt text.
    for dropped in ("0.2", "0.3", "document_id", "entity_id", "0.97"):
        assert dropped not in rendered, f"{dropped} should not reach the model"


def test_prompt_is_budgeted_and_num_ctx_is_explicit():
    """Left to itself Ollama picks a context window and silently truncates the
    front of anything longer — which is where the rules and the evidence are.
    A budgeted prompt that does not pin num_ctx is not budgeted at all."""
    from app.services.context import assemble, model_window

    rows = [
        {"source_type": "graph", "entity": f"P-{i:03d}",
         "relation": "HAS_INSTRUMENT", "target": f"PI-{i:03d}",
         "confidence": 0.9}
        for i in range(400)
    ]
    history = [
        {"role": "user", "content": "tell me about the unit " + "x" * 4000},
        {"role": "assistant", "content": "y" * 6000},
    ] * 10

    messages, options, report = assemble(
        model="gemma3:1b",
        num_predict=320,
        system="stay grounded",
        question="what instruments are on P-001?",
        answer_context=rows,
        history=history,
    )

    window = model_window("gemma3:1b")
    assert options["num_ctx"] == window
    # Everything sent must fit inside the window with the answer's reserve
    # still free, or the model reads a truncated prompt.
    assert report.prompt_tokens <= window - report.reserve_for_answer
    assert report.evidence_total == 400
    assert 0 < report.evidence_kept < 400
    assert report.history_turns_digested > 0
    # The tag that was actually asked about survives the cut.
    assert any("P-001" in m["content"] for m in messages)


def test_thread_context_fills_gaps_but_does_not_overrule_the_request():
    """Follow-ups need the thread ("now make that a PDF" names no subject),
    but borrowing it unconditionally let the previous turn's words win: asked
    for a PDF about P-101 right after an excel of all instruments, the agent
    produced an instrument spreadsheet."""
    from app.services.agent import (
        FORMAT_DOCX,
        FORMAT_PDF,
        FORMAT_XLSX,
        TASK_GROUNDED_DOC,
        TASK_TRACKER,
        _resolve_format,
        _with_context,
        classify_task,
    )

    history = [
        {"role": "user", "content": "Generate excel file of all instruments"},
        {"role": "assistant", "content": "I built a.xlsx"},
    ]

    def route(prompt):
        in_context = _with_context(prompt, history)
        task = classify_task(in_context)
        return task, _resolve_format(prompt, in_context, task)

    # Names its own subject and format: the thread must not touch either.
    assert route("make me a pdf report on P-101") == (
        TASK_GROUNDED_DOC,
        FORMAT_PDF,
    )
    # Names only a format: subject comes from the thread, format from here.
    assert route("now make that a PDF") == (TASK_TRACKER, FORMAT_PDF)
    assert route("also as a word doc") == (TASK_TRACKER, FORMAT_DOCX)
    # Names neither: the thread supplies both.
    assert route("give me the same thing") == (TASK_TRACKER, FORMAT_XLSX)


def test_thread_context_is_only_borrowed_by_an_actual_follow_up():
    """Borrowing the thread whenever the sentence named no plant subject was
    too eager: "make a spreadsheet of the top vision models", asked after an
    instrument tracker, inherited "all instruments" and produced an instrument
    tracker instead of what was asked for."""
    from app.services.agent import (
        TASK_GENERAL_DOC,
        TASK_TRACKER,
        _with_context,
        classify_task,
    )

    history = [
        {"role": "user", "content": "Generate excel file of all instruments"},
        {"role": "assistant", "content": "built a.xlsx"},
        {"role": "user", "content": "now make that a PDF"},
        {"role": "assistant", "content": "built b.pdf"},
    ]

    # A back-reference, or a phrase too short to stand alone, is a follow-up.
    for follow_up in ("now make that a PDF", "also as a word doc", "as a PDF"):
        resolved = _with_context(follow_up, history)
        assert resolved != follow_up, follow_up
        # And it reaches past the middle turn, which names no subject either,
        # so a two-hop chain does not lose the instruments.
        assert "instruments" in resolved, follow_up
        assert classify_task(resolved) == TASK_TRACKER

    # A self-contained request about something else is not a follow-up.
    for fresh in (
        "make a spreadsheet of the top vision models",
        "write a report on transformer architectures",
    ):
        assert _with_context(fresh, history) == fresh
        assert classify_task(fresh) == TASK_GENERAL_DOC
