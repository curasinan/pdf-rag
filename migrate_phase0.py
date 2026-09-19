#!/usr/bin/env python3
"""One-shot Phase 0 migration: add `project="capstone"` to every existing chunk.

Run once after pulling Phase 0 changes. Safe to re-run (idempotent).

Usage:
    python migrate_phase0.py             # dry run, prints what would change
    python migrate_phase0.py --commit    # actually writes the new metadata
"""

import argparse
import sys
import os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vectorstore import get_collection


TARGET_PROJECT = "capstone"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true",
                        help="Actually update metadata. Without this, runs as a dry-run.")
    parser.add_argument("--target", default=TARGET_PROJECT,
                        help=f"Project name to assign to chunks missing one (default: {TARGET_PROJECT}).")
    args = parser.parse_args()

    coll = get_collection()
    total = coll.count()
    if total == 0:
        print("Collection is empty. Nothing to migrate.")
        return

    print(f"Collection has {total} chunks total.")
    data = coll.get(include=["metadatas"])
    ids = data["ids"]
    metas = data["metadatas"]

    needs_update = []
    already_set = []
    for cid, m in zip(ids, metas):
        if m.get("project"):
            already_set.append((cid, m["project"]))
        else:
            needs_update.append((cid, m))

    print(f"  Already have a project: {len(already_set)}")
    print(f"  Missing project (will be set to '{args.target}'): {len(needs_update)}")

    if not needs_update:
        print("Nothing to do.")
        return

    if not args.commit:
        print("\nDry run. Re-run with --commit to apply.")
        # Show a sample of what will change
        for cid, _ in needs_update[:5]:
            print(f"  → {cid}: project = '{args.target}'")
        if len(needs_update) > 5:
            print(f"  ... and {len(needs_update) - 5} more")
        return

    # Apply update in a single batched call
    new_ids = [cid for cid, _ in needs_update]
    new_metas = []
    for _, m in needs_update:
        new_meta = dict(m)
        new_meta["project"] = args.target
        new_metas.append(new_meta)

    coll.update(ids=new_ids, metadatas=new_metas)
    print(f"\nMigrated {len(needs_update)} chunks to project='{args.target}'.")


if __name__ == "__main__":
    main()
