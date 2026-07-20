"""Analyze flow: work_dir resolution, resumable upload, lifecycle, refusals."""

import json
import time

import pytest

httpx = pytest.importorskip("httpx", reason="cloud extra (httpx) not installed")

from showrunner.cloud import analyze  # noqa: E402
from showrunner.cloud.client import CloudClient  # noqa: E402
from showrunner.cloud.credentials import Credentials, CredentialStore  # noqa: E402

SERVER = "https://api.example.test"
UPLOAD_URL = "https://storage.example.test/signed/abc"


# ── input resolution ─────────────────────────────────────────────────


def test_resolve_plain_file(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    assert analyze.resolve_video_path(video) == video


def test_resolve_work_dir_from_manifest(tmp_path):
    out = tmp_path / "output" / "final.mp4"
    out.parent.mkdir()
    out.write_bytes(b"x")
    work = tmp_path / "work"
    work.mkdir()
    (work / "showrunner.json").write_text(json.dumps({"output_path": str(out)}))
    assert analyze.resolve_video_path(work) == out


def test_resolve_work_dir_manifest_relative_path(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "final.mp4").write_bytes(b"x")
    (work / "showrunner.json").write_text(json.dumps({"output_path": "final.mp4"}))
    assert analyze.resolve_video_path(work) == work / "final.mp4"


def test_resolve_work_dir_stale_manifest_falls_back_to_refined(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "showrunner.json").write_text(
        json.dumps({"output_path": "/nonexistent/final.mp4"})
    )
    (work / "refined.mp4").write_bytes(b"x")
    assert analyze.resolve_video_path(work) == work / "refined.mp4"


def test_resolve_work_dir_newest_top_level_mp4(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    old = work / "old.mp4"
    old.write_bytes(b"x")
    new = work / "new.mp4"
    new.write_bytes(b"y")
    import os

    os.utime(old, (time.time() - 100, time.time() - 100))
    assert analyze.resolve_video_path(work) == new


def test_resolve_empty_work_dir_errors_actionably(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(analyze.AnalyzeError, match="Could not find a rendered video"):
        analyze.resolve_video_path(work)


def test_guess_content_type():
    from pathlib import Path

    assert analyze.guess_content_type(Path("a.mp4")) == "video/mp4"
    assert analyze.guess_content_type(Path("a.MOV")) == "video/quicktime"
    assert analyze.guess_content_type(Path("a.webm")) == "video/webm"
    assert analyze.guess_content_type(Path("a.mystery")) == "video/mp4"


# ── refusal messages ─────────────────────────────────────────────────


def test_refusal_file_too_large_includes_limit():
    msg = analyze.refusal_message(
        "file_too_large", {"max_size_bytes": 500 * 1024 * 1024}
    )
    assert "500 MB" in msg


def test_refusal_quota_exceeded():
    assert "quota" in analyze.refusal_message("quota_exceeded", {}).lower()


def test_refusal_unsupported_type_lists_allowed():
    msg = analyze.refusal_message(
        "unsupported_content_type", {"allowed_content_types": ["video/mp4"]}
    )
    assert "video/mp4" in msg


# ── resumable upload ─────────────────────────────────────────────────


class FakeGCS:
    """Signed-URL upload target speaking the GCS resumable protocol."""

    def __init__(self, size: int, fail_times: int = 0):
        self.size = size
        self.committed = 0
        self.requests = []
        self.fail_times = fail_times  # 503 the first N data chunks

    def transport(self):
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        content_range = request.headers.get("Content-Range", "")
        self.requests.append(content_range)
        if content_range.startswith("bytes */"):
            # offset query
            if self.committed >= self.size:
                return httpx.Response(200)
            headers = {"Range": f"bytes=0-{self.committed - 1}"} if self.committed else {}
            return httpx.Response(308, headers=headers)
        if self.fail_times > 0:
            self.fail_times -= 1
            return httpx.Response(503)
        spec, total = content_range.removeprefix("bytes ").split("/")
        start, end = (int(x) for x in spec.split("-"))
        assert start == self.committed, f"non-contiguous chunk {content_range}"
        assert len(request.content) == end - start + 1
        self.committed = end + 1
        if self.committed >= int(total):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(308, headers={"Range": f"bytes=0-{self.committed - 1}"})


def _video(tmp_path, size=100):
    video = tmp_path / "clip.mp4"
    video.write_bytes(bytes(range(256)) * (size // 256) + bytes(size % 256))
    return video


def test_resumable_put_single_chunk(tmp_path):
    video = _video(tmp_path, 100)
    gcs = FakeGCS(100)
    events = []
    analyze.resumable_put(
        UPLOAD_URL, video, 100, "video/mp4",
        on_event=events.append, chunk_size=1024, transport=gcs.transport(),
    )
    assert gcs.committed == 100
    assert gcs.requests == ["bytes 0-99/100"]
    assert [e["bytes_sent"] for e in events] == [0, 100]
    assert events[-1]["pct"] == 100.0


def test_resumable_put_chunked_with_progress(tmp_path):
    video = _video(tmp_path, 100)
    gcs = FakeGCS(100)
    events = []
    analyze.resumable_put(
        UPLOAD_URL, video, 100, "video/mp4",
        on_event=events.append, chunk_size=40, transport=gcs.transport(),
    )
    assert gcs.committed == 100
    assert gcs.requests == ["bytes 0-39/100", "bytes 40-79/100", "bytes 80-99/100"]
    assert [e["bytes_sent"] for e in events] == [0, 40, 80, 100]
    assert all(e["event"] == "upload_progress" for e in events)
    assert all(e["total_bytes"] == 100 for e in events)


def test_resumable_put_resumes_after_transient_failure(tmp_path):
    video = _video(tmp_path, 100)
    gcs = FakeGCS(100, fail_times=1)
    sleeps = []
    analyze.resumable_put(
        UPLOAD_URL, video, 100, "video/mp4",
        chunk_size=40, sleep=sleeps.append, transport=gcs.transport(),
    )
    assert gcs.committed == 100
    assert sleeps  # backed off at least once
    # first data chunk 503'd, then an offset query, then a successful retry
    assert gcs.requests[0] == "bytes 0-39/100"
    assert "bytes */100" in gcs.requests


def test_resumable_put_gives_up_after_max_retries(tmp_path):
    video = _video(tmp_path, 100)
    gcs = FakeGCS(100, fail_times=999)
    with pytest.raises(analyze.AnalyzeError, match="retries"):
        analyze.resumable_put(
            UPLOAD_URL, video, 100, "video/mp4",
            chunk_size=40, sleep=lambda s: None, transport=gcs.transport(),
        )


def test_resumable_put_hard_rejection_mentions_expiry(tmp_path):
    video = _video(tmp_path, 100)
    transport = httpx.MockTransport(lambda r: httpx.Response(403))
    with pytest.raises(analyze.AnalyzeError, match="expired"):
        analyze.resumable_put(
            UPLOAD_URL, video, 100, "video/mp4", transport=transport,
        )


def test_resumable_put_empty_file(tmp_path):
    video = tmp_path / "empty.mp4"
    video.write_bytes(b"")
    with pytest.raises(analyze.AnalyzeError, match="empty"):
        analyze.resumable_put(UPLOAD_URL, video, 0, "video/mp4")


# ── full lifecycle ───────────────────────────────────────────────────


ANALYSIS = {
    "executive_summary": "A tight explainer.",
    "hooks": [{"text": "What if cats could talk?"}],
    "scenes": [{"description": "Intro", "start_time": 0}],
    "content_themes": ["cats", "science"],
    "video_analysis": "Fast cuts, strong typography.",
}


class FakeAnalysisAPI:
    """Mocked /api/v1/analysis/uploads endpoints."""

    def __init__(self, pending_polls=2):
        self.pending_polls = pending_polls
        self.create_body = None
        self.completed = False
        self.polls = 0
        self.refuse_with: dict | None = None
        self.fail_result: dict | None = None

    def transport(self):
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/analysis/uploads" and request.method == "POST":
            self.create_body = json.loads(request.content)
            if self.refuse_with is not None:
                return httpx.Response(400, json=self.refuse_with)
            return httpx.Response(200, json={
                "upload_id": "up-1",
                "upload_url": UPLOAD_URL,
                "expires_in_seconds": 900,
            })
        if path == "/api/v1/analysis/uploads/up-1/complete":
            self.completed = True
            return httpx.Response(200, json={
                "upload_id": "up-1", "status": "pending", "retry_after_seconds": 7,
            })
        if path == "/api/v1/analysis/uploads/up-1" and request.method == "GET":
            self.polls += 1
            if self.fail_result is not None:
                return httpx.Response(200, json=self.fail_result)
            if self.polls <= self.pending_polls:
                status = "pending" if self.polls == 1 else "analyzing"
                return httpx.Response(200, json={
                    "status": status, "retry_after_seconds": 3,
                })
            return httpx.Response(200, json={"status": "done", "analysis": ANALYSIS})
        raise AssertionError(f"unexpected request: {request.method} {path}")


def _client(tmp_path, api: FakeAnalysisAPI) -> CloudClient:
    store = CredentialStore(path=tmp_path / "creds.json", use_keyring=False)
    store.save(Credentials(
        server_url=SERVER, access_token="at-1", refresh_token="rt-1",
        expires_at=time.time() + 3600,
    ))
    return CloudClient(SERVER, store=store, transport=api.transport())


def test_full_lifecycle(tmp_path):
    api = FakeAnalysisAPI(pending_polls=2)
    gcs = FakeGCS(100)
    events, sleeps = [], []
    with _client(tmp_path, api) as client:
        result = analyze.upload_and_analyze(
            client, _video(tmp_path, 100),
            on_event=events.append, chunk_size=40,
            sleep=sleeps.append, upload_transport=gcs.transport(),
        )
    assert result == ANALYSIS
    assert api.create_body == {
        "filename": "clip.mp4", "size_bytes": 100, "content_type": "video/mp4",
    }
    assert api.completed
    assert gcs.committed == 100
    names = [e["event"] for e in events]
    assert names == [
        "upload_progress", "upload_progress", "upload_progress", "upload_progress",
        "analysis_pending",  # from complete
        "analysis_pending", "analysis_pending",  # pending, analyzing polls
    ]
    # retry_after_seconds honored: first poll waits the complete's 7s,
    # subsequent polls the poll responses' 3s.
    assert sleeps == [7.0, 3.0, 3.0]
    statuses = [e["status"] for e in events if e["event"] == "analysis_pending"]
    assert statuses == ["pending", "pending", "analyzing"]


def test_soft_refusal_on_create(tmp_path):
    api = FakeAnalysisAPI()
    api.refuse_with = {"reason": "file_too_large", "max_size_bytes": 1024}
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.SoftRefusal) as exc:
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100), sleep=lambda s: None,
            )
    assert exc.value.reason == "file_too_large"
    assert "too large" in str(exc.value)


def test_failed_analysis_raises_with_reason(tmp_path):
    api = FakeAnalysisAPI()
    api.fail_result = {"status": "failed", "reason": "corrupt_video", "retryable": False}
    gcs = FakeGCS(100)
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalysisFailed, match="corrupt_video") as exc:
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100),
                sleep=lambda s: None, upload_transport=gcs.transport(),
            )
    assert exc.value.retryable is False


def test_failed_analysis_retryable_suggests_retry(tmp_path):
    api = FakeAnalysisAPI()
    api.fail_result = {"status": "failed", "reason": "worker_oom", "retryable": True}
    gcs = FakeGCS(100)
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalysisFailed, match="again"):
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100),
                sleep=lambda s: None, upload_transport=gcs.transport(),
            )


def test_timeout_polling(tmp_path):
    api = FakeAnalysisAPI(pending_polls=10_000)
    gcs = FakeGCS(100)
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="Timed out"):
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100),
                sleep=lambda s: None, upload_transport=gcs.transport(),
                max_wait_seconds=10,
            )


def test_bearer_and_surface_on_analysis_requests(tmp_path):
    seen = []
    api = FakeAnalysisAPI(pending_polls=0)
    inner = api.handler

    def spy(request):
        seen.append((request.url.path, request.headers.get("Authorization"),
                     request.headers.get("X-Client-Surface")))
        return inner(request)

    api.transport = lambda: httpx.MockTransport(spy)
    gcs = FakeGCS(100)
    with _client(tmp_path, api) as client:
        analyze.upload_and_analyze(
            client, _video(tmp_path, 100),
            sleep=lambda s: None, upload_transport=gcs.transport(),
        )
    assert all(auth == "Bearer at-1" and surface == "cli" for _, auth, surface in seen)


# ── human rendering ──────────────────────────────────────────────────


def test_render_analysis_sections():
    text = analyze.render_analysis(ANALYSIS)
    assert "A tight explainer." in text
    assert "What if cats could talk?" in text
    assert "Scenes (1)" in text
    assert "cats, science" in text
    assert "Fast cuts, strong typography." in text


def test_render_analysis_empty_payload():
    assert "raw payload" in analyze.render_analysis({})


def test_render_analysis_unknown_item_shapes():
    text = analyze.render_analysis({
        "hooks": ["plain string hook"],
        "scenes": [{"weird_key": "value"}],
    })
    assert "plain string hook" in text
    assert "weird_key: value" in text
