from __future__ import annotations

from fastapi.testclient import TestClient

from upsell_poc import jobs
from upsell_poc.api import main, public
from upsell_poc.config import Settings
from upsell_poc.schemas import JobStatus
from upsell_poc.storage import get_storage

REPORT = {
    "job_id": "j1",
    "duration_s": 10.0,
    "transcription_provider": "openai",
    "spent_usd": 1.5,
    "budget_usd": 5.0,
    "unpriced_calls": 2,
    "calls": [{"step": "x", "provider": "openai", "model": "m", "cost_usd": 0.1}],
    "conversations": [
        {"conversation_id": 0, "analyzed_by": "m", "escalated": True, "budget_note": "over $1 cap", "topic": "t"},
        {"conversation_id": 1, "analyzed_by": None, "escalated": False, "budget_note": None, "topic": "u"},
    ],
}
TRANSCRIPT = {
    "duration": 3.0,
    "segments": [{"id": 0, "text": "hi"}],
    "provider": "openai",
    "model": "gpt",
    "chunks": 1,
    "acoustics": [{}],
    "roles": {},
}


def _status(**kw) -> JobStatus:
    base = {
        "job_id": "j1",
        "status": "completed",
        "filename": "a.mp3",
        "input_key": "k",
        "created_at": "t",
        "updated_at": "t",
        "spent_usd": 2.0,
        "budget_usd": 9.0,
    }
    return JobStatus(**{**base, **kw})


def test_public_status_hides_spend():
    out = public.public_status(_status())
    assert "spent_usd" not in out and "budget_usd" not in out
    assert out["job_id"] == "j1" and out["status"] == "completed"


def test_public_status_scrubs_dollar_error():
    out = public.public_status(_status(status="failed", error="Stopped: spend reached $5.00"))
    assert out["error"] == public.INCOMPLETE_ERROR
    assert public.public_status(_status(status="failed", error="boom"))["error"] == "boom"


def test_public_report_strips_internals_but_not_input():
    out = public.public_report(REPORT)
    for k in ("spent_usd", "budget_usd", "unpriced_calls", "calls", "transcription_provider"):
        assert k not in out
    assert out["duration_s"] == 10.0
    first, second = out["conversations"]
    assert "analyzed_by" not in first and "escalated" not in first
    assert first["budget_note"] == public.INCOMPLETE_NOTE  # still truthy for the UI
    assert second["budget_note"] is None
    assert "calls" in REPORT and "analyzed_by" in REPORT["conversations"][0]  # input untouched


def test_public_transcript_strips_provider_model_acoustics_roles():
    out = public.public_transcript(TRANSCRIPT)
    assert set(out) == {"duration", "segments", "chunks"}


def test_http_endpoints_hide_internals_store_keeps_them(settings: Settings, tmp_path):
    storage = get_storage(settings)
    f = tmp_path / "x.wav"
    f.write_bytes(b"data")
    status = jobs.create_job(storage, f, "x.wav")
    jobs.update_status(storage, status.job_id, status="completed", spent_usd=3.0)
    storage.put_json(jobs.report_key(status.job_id), REPORT)
    storage.put_json(jobs.transcript_key(status.job_id), TRANSCRIPT)

    old = main.settings
    main.settings = settings
    try:
        client = TestClient(main.app)
        listed = client.get("/api/jobs").json()
        assert listed and all("spent_usd" not in j and "budget_usd" not in j for j in listed)
        one = client.get(f"/api/jobs/{status.job_id}").json()
        assert "spent_usd" not in one and "budget_usd" not in one
        report = client.get(f"/api/jobs/{status.job_id}/report").json()
        assert "calls" not in report and "spent_usd" not in report
        assert "provider" not in client.get(f"/api/jobs/{status.job_id}/transcript").json()
        cancelled = client.post(f"/api/jobs/{status.job_id}/cancel")
        assert cancelled.status_code == 409  # completed: nothing to cancel
    finally:
        main.settings = old

    # Internal copies are untouched.
    assert storage.get_json(jobs.report_key(status.job_id))["calls"] == REPORT["calls"]
    stored_status = jobs.get_status(storage, status.job_id)
    assert stored_status is not None and stored_status.spent_usd == 3.0


def test_default_storage_is_sample_data(monkeypatch):
    monkeypatch.delenv("LOCAL_STORAGE_DIR", raising=False)
    s = Settings(_env_file=None)
    assert s.local_storage_dir.parts[-2:] == ("sample_data", "store")


def test_public_transcript_also_strips_the_nested_provider_and_model():
    stored = {
        "transcript": {"duration": 5, "segments": [], "provider": "openai:gpt-4o-transcribe-diarize", "model": "gpt-4o-transcribe-diarize", "chunks": 1},
        "roles": {"x": 1},
        "acoustics": [],
    }
    out = public.public_transcript(stored)
    assert out == {"transcript": {"duration": 5, "segments": [], "chunks": 1}}


def test_public_status_hides_the_internal_storage_path():
    status = JobStatus(job_id="a", status="queued", filename="x.wav", input_key="jobs/a/input/x.wav", created_at="t", updated_at="t")
    assert "input_key" not in public.public_status(status)


def test_public_status_replaces_crash_text_with_plain_words():
    def err(text):
        st = JobStatus(job_id="a", status="failed", filename="x", input_key="k", created_at="t", updated_at="t", error=text)
        return public.public_status(st)["error"]

    assert err("AudioError: ffmpeg failed: Error opening input file /tmp/upsell-poc/x/a.mp3") == public.AUDIO_ERROR
    assert err("AuthenticationError: Incorrect API key provided: sk-proj-****abcd") == public.FAILED_ERROR
    assert "sk-" not in err("openai.RateLimitError: quota sk-live")
    friendly = "This was interrupted when the app restarted. Press Try again."
    assert err(friendly) == friendly  # our own plain messages are kept
