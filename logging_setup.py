"""Centralized logging configuration.

One module, one function: `setup_logging(verbose=False)`. Called once from `rag.py`
before any pipeline code runs. After that, every module just does:

    import logging
    logger = logging.getLogger(__name__)

and uses `logger.info / logger.debug / logger.error / logger.warning` as usual.

Behavior
========
- INFO by default; DEBUG when `verbose=True`.
- Console handler: human-readable, no timestamps (those clutter the CLI).
- File handler: rotating `data/logs/rag.log` (5 MB × 3 backups), with timestamps.
- Tames the noisy huggingface / sentence-transformers / chromadb loggers down to
  WARNING so the verbose flag actually shows our debug lines, not their model-load
  spam.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import DATA_DIR


_NOISY_LIBS = (
    "httpx",
    "httpcore",
    "urllib3",
    "huggingface_hub",
    "sentence_transformers",
    "transformers",
    "chromadb",
    "openpyxl",
)


def setup_logging(verbose: bool = False) -> None:
    """Configure root logger. Idempotent — calling twice is safe."""
    level = logging.DEBUG if verbose else logging.INFO

    log_dir = Path(DATA_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(levelname)-7s %(name)-12s %(message)s"))

    fileh = RotatingFileHandler(
        log_dir / "rag.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    fileh.setLevel(logging.DEBUG)  # file always captures everything
    fileh.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)-15s %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # let handlers filter
    # Replace any prior handlers to keep this idempotent
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(fileh)

    # Quiet down third-party libs that would otherwise dominate --verbose
    for name in _NOISY_LIBS:
        logging.getLogger(name).setLevel(logging.WARNING)
