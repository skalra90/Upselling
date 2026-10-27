"""Client-facing views of stored data.

Stored files (status, report, transcript) keep the full internal detail - spend, per-call
logs, provider/model names - for debugging and billing. Nothing in this module changes
them: these helpers build the *copies* that leave over HTTP, with internals removed.
"""

from __future__ import annotations

import re
from typing import Any

from upsell_poc.schemas import JobStatus

INCOMPLETE_NOTE = "analysis incomplete"
INCOMPLETE_ERROR = "analysis stopped before it could finish"
AUDIO_ERROR = "We couldn't read this recording. Please record it again, or use a different file."
FAILED_ERROR = "Something went wrong while processing this recording. Please try again."
_CRASH = re.compile(r"^[A-Za-z_.]*(Error|Exception): ")  # how a crash is stored: "ValueError: details..."

STATUS_HIDDEN = {"spent_usd", "budget_usd", "input_key"}  # input_key is the server's internal storage path
REPORT_HIDDEN = {"spent_usd", "budget_usd", "unpriced_calls", "calls", "transcription_provider"}
CONVERSATION_HIDDEN = {"analyzed_by", "escalated"}
TRANSCRIPT_HIDDEN = {"provider", "model", "acoustics", "roles"}


def public_status(status: JobStatus) -> dict[str, Any]:
    out = status.model_dump(exclude=STATUS_HIDDEN)
    # A budget stop's message quotes dollar amounts.
    if out.get("error") and "$" in out["error"]:
        out["error"] = INCOMPLETE_ERROR
    # A crash message is technical: it can hold server paths, provider names or part of a key. Show plain words instead
    # (the full text stays in the stored status for debugging).
    elif out.get("error") and _CRASH.match(out["error"]):
        out["error"] = AUDIO_ERROR if out["error"].startswith("AudioError") else FAILED_ERROR
    return out


def public_conversation(conv: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in conv.items() if k not in CONVERSATION_HIDDEN}
    if out.get("budget_note"):
        out["budget_note"] = INCOMPLETE_NOTE
    return out


def public_report(report: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in report.items() if k not in REPORT_HIDDEN}
    if isinstance(out.get("conversations"), list):
        out["conversations"] = [public_conversation(c) for c in out["conversations"]]
    return out


def public_transcript(transcript: dict[str, Any]) -> dict[str, Any]:
    """The stored file wraps the words in a "transcript" object that carries the provider and model too: strip both levels."""
    out = {k: v for k, v in transcript.items() if k not in TRANSCRIPT_HIDDEN}
    if isinstance(out.get("transcript"), dict):
        out["transcript"] = {k: v for k, v in out["transcript"].items() if k not in TRANSCRIPT_HIDDEN}
    return out
