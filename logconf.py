"""Central logging setup for the whole pipeline. One root log file.

Call `setup_logging()` once from an entry point (each `run.py` main). Library
modules never configure logging — they only do `log = logging.getLogger(__name__)`
and log. The logger name (`ingest.download`, `retrieval.search`, `tools.facts`)
tags every line, so one file shows which folder emitted what, in causal order.

Console shows INFO and up (live progress + warnings + errors). The file keeps
the full DEBUG trace (resolved XBRL tags, per-query hits, retry attempts) so a
bad citation stays diagnosable after the run. The file rotates at ~2 MB.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "verify_ai.log"

_configured = False


def setup_logging() -> None:
    """Configure the root logger: INFO to console, DEBUG to `logs/verify_ai.log`.
    Idempotent — safe to call from every entry point and repeatedly."""
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    fileh = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fileh.setLevel(logging.DEBUG)
    fileh.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )

    root.addHandler(console)
    root.addHandler(fileh)
    _configured = True


if __name__ == "__main__":  # self-check: file is created and captures a line
    setup_logging()
    setup_logging()  # second call must be a no-op (idempotent)
    logging.getLogger("logconf.demo").info("logging configured")
    assert LOG_FILE.exists(), LOG_FILE
    assert len(logging.getLogger().handlers) == 2, "double-configured"
    print(f"self-check: ok -> {LOG_FILE}")
