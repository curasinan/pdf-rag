"""Answer cache and per-question checkpointing for eval runs.

Two problems this solves, both learned the hard way on this machine:

**1. A session limit mid-run destroyed everything.** ``run_eval`` accumulated
results in a list and wrote ``results_hard.json`` once, after the loop. A limit
at question 20 lost twenty questions of Opus generation and sixty judge calls;
only the per-question traces survived, and traces carry no judge scores.
:class:`Checkpoint` appends one JSON line per completed question, so ``--resume``
picks up where the run died.

**2. Re-judging forced re-generation.** For an ablation the answers are the
expensive part and the judge is the part you iterate on. :class:`AnswerCache`
keys generated answers by (arm, question, model, prompt, arm config) so a judge
change, a metric change, or a crash costs nothing to recover from.

Deliberately NOT cached: any production that errored. Caching a failure would
bake an infrastructure outage into every later run.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.arms import Production                                   # noqa: E402


def _key(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _safe_name(qid: str) -> str:
    """Question ids are author-controlled; keep them filesystem-safe anyway."""
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(qid))[:64]


# ── Answer cache ─────────────────────────────────────────────────────


class AnswerCache:
    """Content-addressed store of generated answers, one JSON file per entry."""

    SCHEMA = 1

    def __init__(self, root: Path, enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled

    def _path(self, arm_name: str, qid: str, key: str) -> Path:
        return self.root / arm_name / f"{_safe_name(qid)}__{key}.json"

    def key_for(self, producer, qid: str, question: str, model: str, prompt_hash_: str) -> str:
        return _key({
            "schema": self.SCHEMA,
            "arm": producer.name,
            "qid": qid,
            "question": question,        # verbatim, so a label edit invalidates the entry
            "model": model,
            "prompt_hash": prompt_hash_,
            "arm_config_hash": producer.config_hash(),
        })

    def load(self, producer, qid: str, key: str) -> Production | None:
        if not self.enabled:
            return None
        path = self._path(producer.name, qid, key)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if raw.get("schema") != self.SCHEMA:
            return None
        telemetry = dict(raw.get("telemetry") or {})
        telemetry["cache_hit"] = True
        return Production(
            answer=raw.get("answer", ""),
            context_chunks=raw.get("context_chunks") or [],
            evidence_text=raw.get("evidence_text", ""),
            telemetry=telemetry,
            retrieval_applicable=bool(raw.get("retrieval_applicable")),
            citation_scope=raw.get("citation_scope", "own"),
        )

    def store(self, producer, qid: str, key: str, question: str, prod: Production) -> None:
        # Never cache a failure: an outage must not become a permanent answer.
        if not self.enabled or prod.error:
            return
        path = self._path(producer.name, qid, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": self.SCHEMA,
            "key": key,
            "arm": producer.name,
            "arm_config_hash": producer.config_hash(),
            "qid": qid,
            "question": question,
            "answer": prod.answer,
            "context_chunks": prod.context_chunks,
            "evidence_text": prod.evidence_text,
            "evidence_sha1": hashlib.sha1(
                (prod.evidence_text or "").encode("utf-8")
            ).hexdigest(),
            "retrieval_applicable": prod.retrieval_applicable,
            "citation_scope": prod.citation_scope,
            "telemetry": prod.telemetry,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(path)        # atomic: a killed run never leaves a half-written entry

    def get_or_produce(self, producer, qid, question, qtype, model, prompt_hash_) -> Production:
        key = self.key_for(producer, qid, question, model, prompt_hash_)
        hit = self.load(producer, qid, key)
        if hit is not None:
            return hit
        prod = producer.produce(question, qtype, qid)
        prod.telemetry.setdefault("cache_hit", False)
        self.store(producer, qid, key, question, prod)
        return prod


# ── Per-question checkpoint ──────────────────────────────────────────


class Checkpoint:
    """Append-only JSONL of completed per-question result records."""

    def __init__(self, path: Path, enabled: bool = True):
        self.path = Path(path)
        self.enabled = enabled

    def load(self, include_errors: bool = False) -> dict[str, dict]:
        """Completed records by question id. Tolerates a truncated final line.

        ERROR rows are excluded by default so ``--resume`` *retries* whatever the
        run died on. Treating them as done would let a transient quota outage
        freeze into a permanent ERROR in the final results — the precise failure
        this checkpoint exists to prevent.
        """
        if not self.enabled or not self.path.exists():
            return {}
        done: dict[str, dict] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue      # a run killed mid-write leaves one partial line
            if not rec.get("id"):
                continue
            if rec.get("verdict") == "ERROR" and not include_errors:
                done.pop(rec["id"], None)
                continue
            done[rec["id"]] = rec
        return done

    def append(self, record: dict) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            fh.flush()
