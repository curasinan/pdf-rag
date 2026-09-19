import logging
import sys
import os

from config import (
    CLAUDE_MODEL_FAST, CLAUDE_MODEL_QUALITY,
    MAX_CONTEXT_CHARS, CHUNKS_PER_BATCH,
    DEFAULT_TOP_K, DEFAULT_PROJECT,
    CHUNKER_VERSION, EMBEDDING_MODEL,
)

logger = logging.getLogger(__name__)
from claude_bridge import call_claude as _call_claude, ClaudeCLIError
from pathlib import Path
from pdf_parser import parse_pdf, file_sha256
from embeddings import embed_texts
from vectorstore import (
    replace_document,
    delete_document,
    list_documents,
    list_projects,
    count_chunks,
    get_chunks_for_source,
    get_source_metadata,
)
from retrieval import hybrid_search
from citations import format_pages_human
import bm25 as bm25_index
from prompts import (
    CHUNK_SUMMARY_SYSTEM, CHUNK_SUMMARY_USER,
    FINAL_SUMMARY_SYSTEM, FINAL_SUMMARY_USER,
    QA_SYSTEM, QA_USER,
    ANALYSIS_SYSTEM, ANALYSIS_USER,
    TEACH_SYSTEM, TEACH_USER,
    QUIZ_SYSTEM, QUIZ_USER,
    CHAT_SYSTEM, CHAT_USER,
)


# ── Claude CLI bridge ────────────────────────────────────────────────


# ── Helpers ──────────────────────────────────────────────────────────


def _ensure_docs(project: str | None = None) -> list[str]:
    docs = list_documents(project=project)
    if not docs:
        scope = f" in project '{project}'" if project else ""
        logger.error("No documents ingested yet%s. Run: python rag.py ingest <path>", scope)
        sys.exit(1)
    return docs


def _resolve_source(doc_name: str | None, project: str | None = None) -> str:
    """Pick a single source for commands that require one (summarize). If only one doc
    is ingested, default to it. Otherwise require --doc."""
    docs = _ensure_docs(project=project)
    if doc_name:
        if doc_name not in docs:
            logger.error("Document '%s' not found. Ingested: %s", doc_name, docs)
            sys.exit(1)
        return doc_name
    if len(docs) == 1:
        return docs[0]
    logger.error("Multiple documents found: %s", docs)
    logger.error("Use --doc <name> to specify which one.")
    sys.exit(1)


def _validate_doc(doc_name: str | None, project: str | None = None) -> None:
    """Fail fast if a --doc was given that isn't ingested (finding F25).

    Without this, a typo'd stem (``--doc Coffee-Shops`` for
    ``why_do_coffee_shops_fail``) matches zero chunks, retrieval returns empty,
    and the model confidently answers "the material doesn't cover this" — a wrong
    answer about the user's own corpus with no error anywhere."""
    if not doc_name:
        return
    docs = list_documents(project=project)
    if doc_name not in docs:
        scope = f" in project '{project}'" if project else ""
        logger.error("Document '%s' not found%s. Ingested: %s", doc_name, scope, docs)
        sys.exit(1)


def _format_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a context string with source + page citations.

    Pages are rendered in human form ("pages 3-5", "page 7") via
    ``citations.format_pages_human`` rather than the raw stored "[3, 4, 5]" — the
    header is the citation format the model learns, and the raw list form was
    unparseable by ``parse_citations`` (finding F10)."""
    parts = []
    for chunk in chunks:
        source = chunk.get("source", "unknown")
        pages = format_pages_human(chunk.get("pages"))
        label = "page" if pages.isdigit() else "pages"
        parts.append(f"[{source}, {label} {pages}]\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


def _retrieve(
    query: str,
    doc_name: str | None,
    project: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    use_rerank: bool = True,
) -> str:
    """One call retrieves + formats + truncates context for the LLM."""
    chunks = hybrid_search(query, top_k=top_k, source=doc_name, project=project,
                           use_rerank=use_rerank)
    context = _format_context(chunks)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS]
    return context


# ── Commands ─────────────────────────────────────────────────────────


def ingest(pdf_path: str, project: str = DEFAULT_PROJECT, force: bool = False) -> bool:
    """Parse, chunk, embed, and store a document. Idempotent: re-ingesting replaces all chunks.

    Cache short-circuit: if a doc with the same source name already has chunks whose
    (file_sha256, chunker_version, embedding_model) match the current file and config,
    skip the work entirely and return False. Otherwise do the full pipeline and return True.

    `force=True` bypasses the cache check (useful for debugging the chunker).
    """
    src_stem = Path(pdf_path).stem
    new_sha = file_sha256(pdf_path)

    if not force:
        existing = get_source_metadata(src_stem, project=project)
        if existing and (
            existing.get("file_sha256") == new_sha
            and existing.get("chunker_version") == CHUNKER_VERSION
            and existing.get("embedding_model") == EMBEDDING_MODEL
        ):
            logger.info(
                "Cached '%s' (project='%s'): file unchanged, chunker v%s, model %s",
                src_stem, project, CHUNKER_VERSION, EMBEDDING_MODEL,
            )
            return False  # nothing was done

    logger.info("Parsing %s...", pdf_path)
    chunks = parse_pdf(pdf_path)
    logger.info("  %d chunks extracted", len(chunks))

    logger.info("Embedding chunks (BGE-M3)...")
    vectors = embed_texts([c["text"] for c in chunks])

    doc_name = chunks[0]["source"]
    replace_document(doc_name, chunks, vectors, project=project, file_sha256=new_sha)
    bm25_index.invalidate()  # force BM25 rebuild on next query

    total_chars = sum(len(c["text"]) for c in chunks)
    est_tokens = total_chars // 4
    logger.info(
        "Ingested '%s' (project='%s'): %d chunks, ~%s tokens",
        doc_name, project, len(chunks), f"{est_tokens:,}",
    )
    return True


def query(question: str, doc_name: str = None, project: str | None = None,
          use_rerank: bool = True):
    """Hybrid retrieve + answer. Searches all docs by default."""
    _ensure_docs(project=project)
    _validate_doc(doc_name, project=project)
    logger.info("Searching (dense + BM25%s)...", " + rerank" if use_rerank else ", NO rerank")
    context = _retrieve(question, doc_name, project=project, top_k=DEFAULT_TOP_K,
                        use_rerank=use_rerank)
    if not context.strip():
        print("No matching content found in the material for this query. "
              "The documents may not cover it — try rephrasing or a broader query.")
        return

    logger.info("Generating answer...")
    answer = _call_claude(
        CLAUDE_MODEL_QUALITY,
        QA_SYSTEM,
        QA_USER.format(context=context, question=question),
    )
    print(answer)


def summarize(doc_name: str = None, project: str | None = None):
    """Map-reduce summarization of a single document."""
    source = _resolve_source(doc_name, project=project)

    chunks = get_chunks_for_source(source, project=project)
    if not chunks:
        logger.warning("No chunks found in this document.")
        return

    all_texts = [c["text"] for c in chunks]
    title = source

    total_chars = sum(len(t) for t in all_texts)
    est_tokens = total_chars // 4

    # Small document: single-pass
    if total_chars <= MAX_CONTEXT_CHARS:
        logger.info("Document fits in context (~%s tokens). Single-pass summary...", f"{est_tokens:,}")
        full_text = "\n\n".join(all_texts)
        summary = _call_claude(
            CLAUDE_MODEL_QUALITY,
            FINAL_SUMMARY_SYSTEM,
            FINAL_SUMMARY_USER.format(title=title, summaries=full_text),
        )
        print(f"\n{summary}")
        return

    # Large document: map-reduce
    logger.info("Large document (~%s tokens). Running map-reduce summarization...", f"{est_tokens:,}")

    batches = [
        all_texts[i:i + CHUNKS_PER_BATCH]
        for i in range(0, len(all_texts), CHUNKS_PER_BATCH)
    ]
    logger.info("  Map phase: %d batches...", len(batches))

    chunk_summaries = []
    for i, batch in enumerate(batches):
        batch_text = "\n\n---\n\n".join(batch)
        summary = _call_claude(
            CLAUDE_MODEL_FAST,
            CHUNK_SUMMARY_SYSTEM,
            CHUNK_SUMMARY_USER.format(text=batch_text),
        )
        chunk_summaries.append(summary)
        logger.info("    Batch %d/%d done", i + 1, len(batches))

    summaries_text = "\n\n---\n\n".join(chunk_summaries)
    while len(summaries_text) > MAX_CONTEXT_CHARS:
        logger.info("  Intermediate reduce (summaries still too large)...")
        reduce_batches = [
            chunk_summaries[i:i + CHUNKS_PER_BATCH]
            for i in range(0, len(chunk_summaries), CHUNKS_PER_BATCH)
        ]
        chunk_summaries = []
        for batch in reduce_batches:
            batch_text = "\n\n---\n\n".join(batch)
            summary = _call_claude(
                CLAUDE_MODEL_FAST,
                CHUNK_SUMMARY_SYSTEM,
                CHUNK_SUMMARY_USER.format(text=batch_text),
            )
            chunk_summaries.append(summary)
        summaries_text = "\n\n---\n\n".join(chunk_summaries)

    logger.info("  Reduce phase: final synthesis...")
    final_summary = _call_claude(
        CLAUDE_MODEL_QUALITY,
        FINAL_SUMMARY_SYSTEM,
        FINAL_SUMMARY_USER.format(title=title, summaries=summaries_text),
    )
    print(f"\n{final_summary}")


def analyze(request: str, doc_name: str = None, project: str | None = None):
    """Hybrid retrieve + structured analysis. Searches all docs by default."""
    _ensure_docs(project=project)
    _validate_doc(doc_name, project=project)
    logger.info("Searching (dense + BM25 + rerank)...")
    context = _retrieve(request, doc_name, project=project, top_k=20)
    if not context.strip():
        print("No matching content found in the material for this request.")
        return

    logger.info("Generating analysis...")
    analysis = _call_claude(
        CLAUDE_MODEL_QUALITY,
        ANALYSIS_SYSTEM,
        ANALYSIS_USER.format(context=context, request=request),
    )
    print(analysis)


def teach(topic: str, doc_name: str = None, project: str | None = None):
    """Hybrid retrieve + tutor-style explanation. Searches all docs by default."""
    _ensure_docs(project=project)
    _validate_doc(doc_name, project=project)
    logger.info("Finding material on: %s...", topic)
    context = _retrieve(topic, doc_name, project=project, top_k=15)
    if not context.strip():
        print(f"No material found on '{topic}' in the documents. "
              "Try a different phrasing or check the topic is covered.")
        return

    logger.info("Preparing explanation...")
    explanation = _call_claude(
        CLAUDE_MODEL_QUALITY,
        TEACH_SYSTEM,
        TEACH_USER.format(context=context, topic=topic),
    )
    print(explanation)


def quiz(
    n_questions: int = 5,
    topic: str = None,
    doc_name: str = None,
    project: str | None = None,
):
    """Generate quiz questions from the study material."""
    _ensure_docs(project=project)
    _validate_doc(doc_name, project=project)

    search_text = topic or "key concepts and important topics"
    logger.info("Gathering material for quiz...")
    context = _retrieve(search_text, doc_name, project=project, top_k=20)
    if not context.strip():
        print("No matching material found to build a quiz from. "
              "Try a different --topic or check the document is ingested.")
        return

    focus = f"Focus on: {topic}" if topic else "Cover the most important concepts across all material."

    logger.info("Generating questions...")
    questions = _call_claude(
        CLAUDE_MODEL_QUALITY,
        QUIZ_SYSTEM,
        QUIZ_USER.format(context=context, n_questions=n_questions, focus=focus),
    )
    print(questions)


def chat(doc_name: str = None, project: str | None = None):
    """Interactive study chat — ask questions back and forth about your material."""
    _ensure_docs(project=project)
    _validate_doc(doc_name, project=project)
    history = []

    scope = f" (project={project})" if project else ""
    logger.info("Study chat started%s. Type 'quit' to exit.", scope)

    while True:
        try:
            message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            logger.info("Chat ended.")
            break

        if not message:
            continue
        if message.lower() in ("quit", "exit", "q"):
            logger.info("Chat ended.")
            break

        # Hybrid retrieval based on the latest message
        context = _retrieve(message, doc_name, project=project, top_k=12)
        if not context.strip():
            print("\nTutor: I couldn't find anything in your material for that. "
                  "Try rephrasing, or check the document is ingested.\n")
            continue

        # Build conversation history string (keep last 10 turns)
        history_str = ""
        for turn in history[-10:]:
            history_str += f"Student: {turn['user']}\nTutor: {turn['assistant']}\n\n"

        # A single flaky CLI call must not kill the chat and lose all history (F15).
        try:
            response = _call_claude(
                CLAUDE_MODEL_QUALITY,
                CHAT_SYSTEM,
                CHAT_USER.format(context=context, history=history_str, message=message),
            )
        except ClaudeCLIError as e:
            print(f"\n[Claude CLI error: {e} — your history is intact; try again.]\n")
            continue

        print(f"\nTutor: {response}\n")
        history.append({"user": message, "assistant": response})


def list_docs(project: str | None = None):
    """Print all ingested documents with chunk counts. Optionally scoped to a project.

    Output goes to stdout (this is data the user wants to read), not the logger."""
    docs = list_documents(project=project)
    if not docs:
        scope = f" in project '{project}'" if project else ""
        print(f"No documents ingested yet{scope}.")
        return
    header = f"Ingested documents (project={project})" if project else "Ingested documents (all projects)"
    print(f"{header}:")
    for d in docs:
        print(f"  - {d} ({count_chunks(d, project=project)} chunks)")


def list_projects_cmd():
    """Print all projects currently in the collection with chunk + doc counts.

    Output goes to stdout (data the user wants to read), not the logger."""
    projects = list_projects()
    if not projects:
        print("No projects ingested yet.")
        return
    print("Projects:")
    for p in projects:
        n_docs = len(list_documents(project=p))
        n_chunks = count_chunks(project=p)
        print(f"  - {p}: {n_docs} docs, {n_chunks} chunks")


def delete_doc(name: str, project: str | None = None):
    """Remove an ingested document and invalidate the BM25 cache.

    When `project` is supplied, the delete is scoped to that project — useful when
    the same source name was ingested into multiple projects."""
    delete_document(name, project=project)
    bm25_index.invalidate()
    scope = f" from project '{project}'" if project else ""
    logger.info("Deleted '%s'%s", name, scope)
