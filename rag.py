#!/usr/bin/env python3
"""PDF RAG Study Tool — Ingest, query, learn from, and quiz yourself on large PDFs via Claude API."""

import argparse
import sys
import os

# Fix Unicode output on Windows terminals
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure imports work when running from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DEFAULT_PROJECT
from logging_setup import setup_logging
from claude_bridge import ClaudeCLIError
from pipeline import (
    ingest, query, summarize, analyze, teach, quiz, chat,
    list_docs, list_projects_cmd, delete_doc,
)


def _add_project_arg(p: argparse.ArgumentParser, default: str | None = DEFAULT_PROJECT):
    """Add a uniform --project flag to a subparser. Default keeps current single-project
    behavior; pass None to default to "all projects" for read-only commands like list."""
    p.add_argument(
        "--project",
        default=default,
        help=f"Project namespace (default: '{default}'). Use to keep multiple study domains separate.",
    )


def main():
    parser = argparse.ArgumentParser(
        description="PDF RAG Study Tool — learn from PDFs that exceed Claude's context limit"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable DEBUG-level logging on stderr (and to data/logs/rag.log).",
    )
    sub = parser.add_subparsers(dest="command")

    # ingest
    p = sub.add_parser("ingest", help="Parse, chunk, embed, and store a PDF/DOCX/XLSX")
    p.add_argument("pdf_path", help="Path to the file (PDF, DOCX, or XLSX)")
    _add_project_arg(p)

    # query
    p = sub.add_parser("query", help="Ask a question (searches all docs by default)")
    p.add_argument("question", help="Your question")
    p.add_argument("--doc", default=None, help="Limit to a specific document")
    p.add_argument("--no-rerank", action="store_true",
                   help="Skip the cross-encoder rerank and answer from the RRF order. "
                        "Rerank is the dominant cost in retrieval latency; this is the "
                        "knob for trading a little ranking quality for a lot of speed.")
    _add_project_arg(p)

    # summarize
    p = sub.add_parser("summarize", help="Generate a full document summary")
    p.add_argument("--doc", default=None, help="Document name (required if multiple)")
    _add_project_arg(p)

    # analyze
    p = sub.add_parser("analyze", help="Perform targeted analysis (searches all docs)")
    p.add_argument("request", help="What to analyze")
    p.add_argument("--doc", default=None, help="Limit to a specific document")
    _add_project_arg(p)

    # teach
    p = sub.add_parser("teach", help="Get a tutor-style explanation of a topic")
    p.add_argument("topic", help="What you want to learn about")
    p.add_argument("--doc", default=None, help="Limit to a specific document")
    _add_project_arg(p)

    # quiz
    p = sub.add_parser("quiz", help="Generate quiz questions to test your knowledge")
    p.add_argument("-n", type=int, default=5, help="Number of questions (default: 5)")
    p.add_argument("--topic", default=None, help="Focus quiz on a specific topic")
    p.add_argument("--doc", default=None, help="Limit to a specific document")
    _add_project_arg(p)

    # chat
    p = sub.add_parser("chat", help="Interactive study chat about your material")
    p.add_argument("--doc", default=None, help="Limit to a specific document")
    _add_project_arg(p)

    # list — defaults to all projects when --project not given
    p = sub.add_parser("list", help="Show all ingested documents")
    _add_project_arg(p, default=None)

    # projects — new subcommand
    sub.add_parser("projects", help="List all projects with their document and chunk counts")

    # delete — defaults to all projects when --project not given (matches old wipe behavior)
    p = sub.add_parser("delete", help="Remove an ingested document")
    p.add_argument("doc_name", help="Document name to delete")
    _add_project_arg(p, default=None)

    args = parser.parse_args()
    setup_logging(verbose=getattr(args, "verbose", False))

    if not args.command:
        parser.print_help()
        return

    try:
        match args.command:
            case "ingest":
                ingest(args.pdf_path, project=args.project)
            case "query":
                query(args.question, args.doc, project=args.project,
                      use_rerank=not args.no_rerank)
            case "summarize":
                summarize(args.doc, project=args.project)
            case "analyze":
                analyze(args.request, args.doc, project=args.project)
            case "teach":
                teach(args.topic, args.doc, project=args.project)
            case "quiz":
                quiz(args.n, args.topic, args.doc, project=args.project)
            case "chat":
                chat(args.doc, project=args.project)
            case "list":
                list_docs(project=args.project)
            case "projects":
                list_projects_cmd()
            case "delete":
                delete_doc(args.doc_name, project=args.project)
    except ClaudeCLIError as e:
        # A CLI failure surfaces as a clean message + non-zero exit, not a raw
        # traceback into subprocess internals (F15/F49).
        print(f"Claude CLI error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
