"""One-shot migration: rewrite legacy {source}::chunk_{seq} IDs into the new
content-stable {source}::{sha1[:12]} IDs (Weekend-3 Phase A2).

Why this exists separately from CHUNKER_VERSION bump
====================================================
Bumping CHUNKER_VERSION (2 → 3) causes pipeline.ingest() to detect a cache miss
and re-run the full ingest pipeline (parse → chunk → embed → upsert) on every
document. That's correct but slow: BGE-M3 has to re-embed 121 chunks, which
takes ~5-10 minutes on CPU. This script is the fast path: it copies each
existing chunk's text/embedding/metadata into a new entry under the stable ID
and deletes the old entry. About 10 seconds total.

When to use which
=================
- Re-ingest (slow path): when chunker output actually changed (config.USE_DOCLING
  flipped, MIN_CHUNK_CHARS changed, parser logic changed). The chunks themselves
  must be regenerated.
- This migration (fast path): when ONLY the ID format changed and chunk text +
  embeddings are identical. That's the case for the v2 → v3 bump.

Usage
=====
    # Dry-run: show what would change
    python migrate_phase_a2.py
    # Commit: actually rewrite IDs
    python migrate_phase_a2.py --commit

After --commit, also bump the chunker_version stored in metadata so subsequent
pipeline.ingest() calls hit the cache and don't redo the work.
"""

from __future__ import annotations

import argparse
import sys

from vectorstore import get_collection, stable_chunk_id
from config import CHUNKER_VERSION, EMBEDDING_MODEL


def migrate(commit: bool = False) -> None:
    coll = get_collection()
    total = coll.count()
    if total == 0:
        print("Collection is empty. Nothing to migrate.")
        return

    # Pull everything in one shot. The capstone corpus is small enough.
    data = coll.get(include=["documents", "metadatas", "embeddings"])
    ids = data["ids"]
    texts = data["documents"]
    metas = data["metadatas"]
    vecs = data["embeddings"]

    # Plan: for every chunk, compute its new stable ID. If different from current,
    # mark for rewrite.
    rewrites = []
    already_stable = 0
    seen_new_ids: dict[str, int] = {}
    for i, old_id in enumerate(ids):
        meta = metas[i]
        source = meta.get("source", "")
        text = texts[i]
        # v4 IDs are project-namespaced — use each chunk's own project metadata.
        project = meta.get("project", "default")
        new_id = stable_chunk_id(source, text, project=project)
        # Same duplicate-content disambiguation add_chunks applies (::N suffix).
        if new_id in seen_new_ids:
            seen_new_ids[new_id] += 1
            new_id = f"{new_id}::{seen_new_ids[new_id]}"
        else:
            seen_new_ids[new_id] = 0
        if new_id == old_id:
            already_stable += 1
            continue
        rewrites.append((old_id, new_id, i))

    print(f"Total chunks:        {total}")
    print(f"Already stable IDs:  {already_stable}")
    print(f"Need rewrite:        {len(rewrites)}")

    if not rewrites:
        print("Nothing to do.")
        return

    # Show a sample of what will change
    print("\nSample (first 5 rewrites):")
    for old_id, new_id, _ in rewrites[:5]:
        print(f"  {old_id!r}\n  → {new_id!r}\n")

    if not commit:
        print("Dry-run. Pass --commit to apply.")
        return

    # Execute. Strategy: add the new entries first, then delete the old ones.
    # We bump the metadata's chunker_version + embedding_model in case any of the
    # legacy chunks predate those fields (defensive).
    new_ids = [r[1] for r in rewrites]
    new_texts = [texts[r[2]] for r in rewrites]
    new_vecs = [vecs[r[2]] for r in rewrites]
    new_metas = []
    for old_id, new_id, idx in rewrites:
        m = dict(metas[idx])
        # Preserve seq so document order is recoverable
        if "chunk_seq" not in m:
            old_chunk_id = m.get("chunk_id")
            # Legacy chunk_id was a numeric string. Salvage it as the seq.
            try:
                m["chunk_seq"] = int(old_chunk_id) if old_chunk_id is not None else None
            except (TypeError, ValueError):
                m["chunk_seq"] = None
        m["chunk_id"] = new_id
        # Refresh version pins so cache logic accepts these as current
        m["chunker_version"] = CHUNKER_VERSION
        m["embedding_model"] = EMBEDDING_MODEL
        new_metas.append(m)

    # Upsert new entries (will overwrite if a stable ID already happens to exist)
    print(f"Upserting {len(rewrites)} entries under stable IDs...")
    coll.upsert(
        ids=new_ids,
        documents=new_texts,
        embeddings=new_vecs,
        metadatas=new_metas,
    )

    # Delete the legacy entries. ChromaDB's delete-by-ids is bulk-safe.
    old_ids = [r[0] for r in rewrites]
    print(f"Deleting {len(old_ids)} legacy entries...")
    coll.delete(ids=old_ids)

    print(f"Done. Collection size now: {coll.count()}")

    # The chunk IDs just changed, so the pickled BM25 index (and any in-memory
    # copy in this process) is stale — invalidate instead of asking the operator to.
    import bm25
    bm25.invalidate()
    print("BM25 index invalidated; it will rebuild on the next query.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true",
                   help="Actually rewrite IDs (default is dry-run).")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    migrate(commit=args.commit)
