"""Tests for batch_ingest.py's folder checks. ``ingest`` is stubbed, so no parser,
embedding model, or ChromaDB is touched."""

import sys
from pathlib import Path

import pytest

import batch_ingest


@pytest.fixture
def ingested(monkeypatch) -> list[str]:
    """Stub ingest; the returned list records every path batch_ingest tried to ingest."""
    calls: list[str] = []
    monkeypatch.setattr(batch_ingest, "ingest",
                        lambda path, project: calls.append(path) or True)
    monkeypatch.setattr(batch_ingest, "setup_logging", lambda verbose: None)
    return calls


def _run(folder: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["batch_ingest.py", str(folder)])
    batch_ingest.main()


def _touch(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def test_shared_name_stops_before_anything_is_ingested(tmp_path, ingested, monkeypatch, capsys):
    """business_plan.pdf and a/business_plan.docx are both stored as 'business_plan';
    ingesting both would leave only whichever came last."""
    _touch(tmp_path, "business_plan.pdf", "a/business_plan.docx", "unrelated.xlsx")
    with pytest.raises(SystemExit) as exc:
        _run(tmp_path, monkeypatch)
    assert exc.value.code == 1
    assert ingested == []
    out = capsys.readouterr().out
    assert str(Path("a") / "business_plan.docx") in out
    assert "business_plan.pdf" in out
    assert "unrelated" not in out


def test_distinct_names_are_all_ingested(tmp_path, ingested, monkeypatch):
    _touch(tmp_path, "x.pdf", "sub/y.docx", "notes.txt")
    _run(tmp_path, monkeypatch)
    assert sorted(Path(p).name for p in ingested) == ["x.pdf", "y.docx"]
