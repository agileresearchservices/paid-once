"""Ports, paths and names shared by every process in the demo."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("RACCOON_ROOT", Path(__file__).resolve().parent.parent))
DATA_DIR = Path(os.environ.get("RACCOON_DATA", ROOT / "data"))

SHOW_PORT = int(os.environ.get("RACCOON_SHOW_PORT", "8100"))
PAYMENTS_PORT = int(os.environ.get("RACCOON_PAYMENTS_PORT", "8101"))
LANE1_PORT = int(os.environ.get("RACCOON_LANE1_PORT", "8102"))

PAYMENTS_URL = os.environ.get(
    "RACCOON_PAYMENTS_URL", f"http://127.0.0.1:{PAYMENTS_PORT}"
)
LANE1_URL = os.environ.get("RACCOON_LANE1_URL", f"http://127.0.0.1:{LANE1_PORT}")

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233")
SUPPORT_NAMESPACE = os.environ.get("RACCOON_SUPPORT_NS", "raccoon-support")
PAYMENTS_NAMESPACE = os.environ.get("RACCOON_PAYMENTS_NS", "raccoon-payments")
SUPPORT_TASK_QUEUE = "support-agent"
PAYMENTS_TASK_QUEUE = "payments-nexus"
NEXUS_ENDPOINT = (
    "payments-endpoint"  # keep in sync with raccoon.lane2.contract.NEXUS_ENDPOINT
)

# The model is a real Anthropic model by default. Tests set RACCOON_STUB_LLM=1.
MODEL = os.environ.get("RACCOON_MODEL", "claude-haiku-5-5")
STUB_LLM = os.environ.get("RACCOON_STUB_LLM", "") == "1"

# Lane 1 queue: a visibility timeout like SQS or Pub/Sub ack deadlines.
VISIBILITY_TIMEOUT_S = float(os.environ.get("RACCOON_VISIBILITY_S", "10"))
# What a typical client does against a slow downstream.
PAYMENTS_CLIENT_TIMEOUT_S = float(os.environ.get("RACCOON_PAYMENTS_TIMEOUT_S", "3"))

LEDGER_DB = DATA_DIR / "ledger.db"
LANE1_DB = DATA_DIR / "lane1.db"
AUDIT_DB = DATA_DIR / "audit.db"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
