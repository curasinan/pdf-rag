#!/usr/bin/env python3
"""Ingest every supported file (.pdf, .docx, .xlsx) under a folder, recursively.

Usage:
    python batch_ingest.py <folder> [--project <name>]
    python batch_ingest.py sources/capstone --project capstone

Behavior:
    - Walks the folder recursively
    - Ingests every .pdf, .docx, .xlsx via the normal pipeline.ingest()
    - Skips unsupported file types with a note
    - On per-file failure, prints the error and continues with the rest
    - Prints a summary at the end
"""

import argparse
import sys
import os
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DEFAULT_PROJECT
from logging_setup import setup_logging
from pdf_parser import SUPPORTED_EXTS
from pipeline import ingest


def main():
    parser = argparse.ArgumentParser(description="Bulk-ingest every supported document under a folder.")
    parser.add_argument("folder", help="Folder to scan recursively")
    parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=f"Project namespace to ingest into (default: '{DEFAULT_PROJECT}').",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG-level logging.")
    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    root = Path(args.folder)
    if not root.exists() or not root.is_dir():
        print(f"Folder not found: {root}")
        sys.exit(1)

    all_files = sorted(p for p in root.rglob("*") if p.is_file())
    supported = [p for p in all_files if p.suffix.lower() in SUPPORTED_EXTS]
    skipped = [p for p in all_files if p.suffix.lower() not in SUPPORTED_EXTS]

    if not supported:
        print(f"No supported files found in {root}. Supported: {sorted(SUPPORTED_EXTS)}")
        sys.exit(1)

    print(f"Found {len(supported)} supported file(s), {len(skipped)} skipped. Project: '{args.project}'.\n")

    ingested: list[str] = []
    cached: list[str] = []
    failed: list[tuple[str, str]] = []

    for i, path in enumerate(supported, 1):
        print(f"[{i}/{len(supported)}] {path.name}")
        try:
            did_work = ingest(str(path), project=args.project)
            if did_work:
                ingested.append(path.name)
            else:
                cached.append(path.name)
                print("  (cached — file unchanged since last ingest)")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            failed.append((path.name, str(e)))
        print()

    print("=" * 60)
    print(f"Project:   {args.project}")
    print(f"Ingested:  {len(ingested)}")
    print(f"Cached:    {len(cached)} (unchanged, skipped)")
    print(f"Failed:    {len(failed)}")
    print(f"Skipped:   {len(skipped)} (unsupported file types)")
    if failed:
        print("\nFailures:")
        for name, err in failed:
            print(f"  - {name}: {err}")
    if skipped:
        print("\nSkipped (unsupported):")
        for p in skipped:
            print(f"  - {p.name}")


if __name__ == "__main__":
    main()
