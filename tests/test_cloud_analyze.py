"""Analyze flow: work_dir resolution, drafts upload, 404-as-pending polling."""

import json
import time

import pytest

httpx = pytest.importorskip("httpx", reason="cloud extra (httpx) not installed")

from showrunner.cloud import analyze  # noqa: E402
from showrunner.cloud.client import CloudClient  # noqa: E402
from showrunner.cloud.credentials import Credentials, CredentialStore  # noqa: E402

SERVER = "https://api.example.test"
POST_ID = "8f2c1f9e-0000-4000-8000-000000000001"


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
    assert analyze.guess_content_type(Path("a.m4v")) == "video/mp4"
    assert analyze.guess_content_type(Path("a.MOV")) == "video/quicktime"
    assert analyze.guess_content_type(Path("a.avi")) == "video/x-msvideo"
    assert analyze.guess_content_type(Path("a.mkv")) == "video/x-matroska"
    assert analyze.guess_content_type(Path("a.webm")) == "video/webm"


def test_check_supported_type_rejects_unknown_extension():
    from pathlib import Path

    with pytest.raises(analyze.AnalyzeError, match="Unsupported video type"):
        analyze.check_supported_type(Path("a.gif"))
    # supported ones pass silently
    analyze.check_supported_type(Path("a.mp4"))
    analyze.check_supported_type(Path("a.MKV"))


# ── mocked drafts API ────────────────────────────────────────────────


ANALYSIS = {
    "executive_summary": "A tight explainer.",
    "hooks": [{"text": "What if cats could talk?"}],
    "scenes": [{"description": "Intro", "start_time": 0}],
    "content_themes": ["cats", "science"],
    "video_analysis": "Fast cuts, strong typography.",
}


def _form_value(request: "httpx.Request", name: str) -> str | None:
    """Extract one multipart form field's value from a captured request."""
    import re

    match = re.search(
        rb'name="' + name.encode() + rb'"\r\n\r\n(.*?)\r\n',
        request.content,
        re.DOTALL,
    )
    return match.group(1).decode() if match else None


class FakeDraftsAPI:
    """Mocked /api/v1/drafts endpoints (multipart upload + 404-poll).

    The upload endpoint is the client-minted-id form of POST
    /api/v1/drafts (fields `post_id` + `file`); the response echoes the
    client's post_id, as the server does. `fail_uploads_with` makes the
    first N upload attempts fail (an int → that HTTP status; an
    exception instance → raised as a transport error) so retry behavior
    can be asserted via `upload_requests`.
    """

    def __init__(self, pending_404s: int = 2):
        self.pending_404s = pending_404s
        self.upload_requests: list[httpx.Request] = []
        self.polls = 0
        self.upload_status: int | None = None  # force a non-201 upload
        self.upload_headers: dict = {}
        self.poll_result: dict | None = None  # override the 200 body
        self.fail_uploads_with = None  # int status or Exception
        self.fail_first_n_uploads = 0

    def transport(self):
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/drafts" and request.method == "POST":
            self.upload_requests.append(request)
            request.read()
            if len(self.upload_requests) <= self.fail_first_n_uploads:
                if isinstance(self.fail_uploads_with, Exception):
                    raise self.fail_uploads_with
                return httpx.Response(
                    self.fail_uploads_with, json={"detail": "flaky"}
                )
            if self.upload_status is not None:
                return httpx.Response(
                    self.upload_status,
                    headers=self.upload_headers,
                    json={"detail": "nope"},
                )
            return httpx.Response(201, json={
                "post_id": _form_value(request, "post_id"), "user_id": "u-1",
            })
        if path.startswith("/api/v1/drafts/") and path.endswith("/analysis") \
                and request.method == "GET":
            self.polls += 1
            if self.polls <= self.pending_404s:
                return httpx.Response(404, json={"detail": "Analysis not found"})
            if self.poll_result is not None:
                return httpx.Response(200, json=self.poll_result)
            return httpx.Response(200, json={
                "post_id": POST_ID, "user_id": "u-1", "analysis": ANALYSIS,
            })
        raise AssertionError(f"unexpected request: {request.method} {path}")


def _client(tmp_path, api: FakeDraftsAPI) -> CloudClient:
    store = CredentialStore(path=tmp_path / "creds.json", use_keyring=False)
    store.save(Credentials(
        server_url=SERVER, access_token="at-1", refresh_token="rt-1",
        expires_at=time.time() + 3600,
    ))
    return CloudClient(SERVER, store=store, transport=api.transport())


def _video(tmp_path, size=100, name="clip.mp4"):
    video = tmp_path / name
    video.write_bytes(bytes(range(256)) * (size // 256) + bytes(range(size % 256)))
    return video


# ── full lifecycle ───────────────────────────────────────────────────


def test_full_lifecycle(tmp_path):
    api = FakeDraftsAPI(pending_404s=2)
    events, sleeps = [], []
    with _client(tmp_path, api) as client:
        result = analyze.upload_and_analyze(
            client, _video(tmp_path, 100),
            on_event=events.append, sleep=sleeps.append,
        )
    assert result == ANALYSIS
    assert api.polls == 3  # two 404s, then the 200

    # multipart upload introspection: client-minted UUID + the file
    assert len(api.upload_requests) == 1
    req = api.upload_requests[0]
    assert req.url.path == "/api/v1/drafts"
    assert req.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    body = req.content
    assert b'name="post_id"' in body
    minted = _form_value(req, "post_id")
    import uuid

    assert uuid.UUID(minted).version == 4  # minted client-side, v4
    assert b'name="video_file"' in body
    assert b'filename="clip.mp4"' in body
    assert b"Content-Type: video/mp4" in body
    assert bytes(range(100)) in body  # the actual video bytes made it through

    # events: progress bracketed 0→100, then pending on start + each 404
    names = [e["event"] for e in events]
    progress = [e for e in events if e["event"] == "upload_progress"]
    pending = [e for e in events if e["event"] == "analysis_pending"]
    assert names[0] == "upload_progress"
    assert progress[0]["bytes_sent"] == 0 and progress[0]["pct"] == 0.0
    assert progress[-1]["bytes_sent"] == 100 and progress[-1]["pct"] == 100.0
    assert all(e["total_bytes"] == 100 for e in progress)
    assert len(pending) == 3  # initial + one per 404
    assert all(e["status"] == "processing" for e in pending)
    assert all(e["post_id"] == minted for e in pending)

    # backoff: 5s, then 7.5s (retries after the first 404's backoff bump)
    assert sleeps == [5.0, 7.5, 11.25]


def test_poll_backoff_caps_at_max_delay(tmp_path):
    api = FakeDraftsAPI(pending_404s=6)
    sleeps = []
    with _client(tmp_path, api) as client:
        analyze.upload_and_analyze(
            client, _video(tmp_path, 100), sleep=sleeps.append,
        )
    assert sleeps == [5.0, 7.5, 11.25, 15.0, 15.0, 15.0, 15.0]


def test_upload_400_unsupported_type_message(tmp_path):
    api = FakeDraftsAPI()
    api.upload_status = 400
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="Supported types"):
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100), sleep=lambda s: None,
            )
    assert api.polls == 0


def test_upload_403_mentions_scope_and_login(tmp_path):
    api = FakeDraftsAPI()
    api.upload_status = 403
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="analysis:upload"):
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100), sleep=lambda s: None,
            )


def test_upload_429_surfaces_retry_guidance(tmp_path):
    api = FakeDraftsAPI()
    api.upload_status = 429
    api.upload_headers = {"Retry-After": "42"}
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="rate limit.*42s"):
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100), sleep=lambda s: None,
            )


def test_upload_429_without_retry_after(tmp_path):
    api = FakeDraftsAPI()
    api.upload_status = 429
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="try again"):
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100), sleep=lambda s: None,
            )


def test_upload_201_without_body_post_id_returns_minted_id(tmp_path):
    """The id is client-minted — a 201 missing the echo still succeeds."""

    def handler(request):
        request.read()
        return httpx.Response(201, json={"user_id": "u-1"})

    api = FakeDraftsAPI()
    api.transport = lambda: httpx.MockTransport(handler)
    with _client(tmp_path, api) as client:
        post_id = analyze.upload(
            client, _video(tmp_path, 100), post_id=POST_ID,
        )
    assert post_id == POST_ID


# ── idempotent retries (same client-minted UUID) ─────────────────────


def test_upload_retries_transport_error_with_same_uuid(tmp_path):
    api = FakeDraftsAPI()
    api.fail_first_n_uploads = 1
    api.fail_uploads_with = httpx.ConnectError("connection reset")
    sleeps = []
    with _client(tmp_path, api) as client:
        post_id = analyze.upload(
            client, _video(tmp_path, 100), sleep=sleeps.append,
        )
    # fail once, then succeed: two requests, the SAME minted post_id,
    # and exactly one successful create.
    assert len(api.upload_requests) == 2
    ids = [_form_value(r, "post_id") for r in api.upload_requests]
    assert ids[0] == ids[1] == post_id
    assert sleeps == [1.0]  # short backoff before the retry


def test_upload_retries_5xx_with_same_uuid_and_events(tmp_path):
    api = FakeDraftsAPI()
    api.fail_first_n_uploads = 1
    api.fail_uploads_with = 503
    events = []
    with _client(tmp_path, api) as client:
        post_id = analyze.upload(
            client, _video(tmp_path, 100),
            on_event=events.append, sleep=lambda s: None,
        )
    assert len(api.upload_requests) == 2
    ids = [_form_value(r, "post_id") for r in api.upload_requests]
    assert ids[0] == ids[1] == post_id
    retries = [e for e in events if e["event"] == "upload_retry"]
    assert len(retries) == 1
    assert retries[0]["post_id"] == post_id
    assert retries[0]["attempt"] == 2
    assert retries[0]["max_attempts"] == analyze.UPLOAD_MAX_ATTEMPTS
    assert "HTTP 503" in retries[0]["reason"]


def test_upload_4xx_is_never_retried(tmp_path):
    api = FakeDraftsAPI()
    api.upload_status = 400
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError):
            analyze.upload(
                client, _video(tmp_path, 100), sleep=lambda s: None,
            )
    assert len(api.upload_requests) == 1  # a 400 fails immediately


def test_upload_exhausts_attempts_with_same_uuid(tmp_path):
    api = FakeDraftsAPI()
    api.fail_first_n_uploads = 10
    api.fail_uploads_with = httpx.ReadError("boom")
    sleeps = []
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="3 attempts") as exc:
            analyze.upload(
                client, _video(tmp_path, 100), sleep=sleeps.append,
            )
    assert len(api.upload_requests) == 3  # bounded
    ids = {_form_value(r, "post_id") for r in api.upload_requests}
    assert len(ids) == 1  # every attempt reused the identical UUID
    assert ids.pop() in str(exc.value)  # the id is surfaced for retry
    assert sleeps == [1.0, 2.0]


def test_upload_accepts_and_reuses_a_provided_post_id(tmp_path):
    api = FakeDraftsAPI()
    with _client(tmp_path, api) as client:
        post_id = analyze.upload(
            client, _video(tmp_path, 100), post_id=POST_ID,
        )
    assert post_id == POST_ID
    assert _form_value(api.upload_requests[0], "post_id") == POST_ID


def test_upload_rejects_a_non_uuid_post_id(tmp_path):
    api = FakeDraftsAPI()
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="UUID"):
            analyze.upload(
                client, _video(tmp_path, 100), post_id="not-a-uuid",
            )
    assert api.upload_requests == []  # rejected before any bytes move


def test_is_valid_post_id():
    assert analyze.is_valid_post_id(POST_ID)
    assert analyze.is_valid_post_id(analyze.mint_post_id())
    assert not analyze.is_valid_post_id("not-a-uuid")
    assert not analyze.is_valid_post_id(None)
    assert not analyze.is_valid_post_id(42)


def test_unsupported_extension_fails_before_upload(tmp_path):
    api = FakeDraftsAPI()
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="Unsupported video type"):
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100, name="clip.gif"),
                sleep=lambda s: None,
            )
    assert api.upload_requests == []


def test_empty_file_fails_before_upload(tmp_path):
    api = FakeDraftsAPI()
    video = tmp_path / "empty.mp4"
    video.write_bytes(b"")
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="empty"):
            analyze.upload_and_analyze(client, video, sleep=lambda s: None)
    assert api.upload_requests == []


def test_failed_status_is_terminal_with_reason(tmp_path):
    api = FakeDraftsAPI(pending_404s=1)
    api.poll_result = {
        "post_id": POST_ID, "user_id": "u-1",
        "status": "failed", "failure_reason": "corrupt_video",
    }
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalysisFailed, match="corrupt_video") as exc:
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100), sleep=lambda s: None,
            )
    assert exc.value.reason == "corrupt_video"
    assert api.polls == 2  # the failed 200 stopped the polling


def test_failed_status_inside_analysis_object(tmp_path):
    api = FakeDraftsAPI(pending_404s=0)
    api.poll_result = {
        "post_id": POST_ID, "user_id": "u-1",
        "analysis": {"status": "failed", "failure_reason": "worker_oom"},
    }
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalysisFailed, match="worker_oom"):
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100), sleep=lambda s: None,
            )


def test_poll_non_404_error_raises(tmp_path):
    def handler(request):
        request.read()
        if request.method == "POST" and request.url.path == "/api/v1/drafts":
            return httpx.Response(201, json={"post_id": POST_ID, "user_id": "u-1"})
        return httpx.Response(500)

    api = FakeDraftsAPI()
    api.transport = lambda: httpx.MockTransport(handler)
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="HTTP 500"):
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100), sleep=lambda s: None,
            )


def test_timeout_polling(tmp_path):
    api = FakeDraftsAPI(pending_404s=10_000)
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="Timed out") as exc:
            analyze.upload_and_analyze(
                client, _video(tmp_path, 100),
                sleep=lambda s: None, max_wait_seconds=30,
            )
    minted = _form_value(api.upload_requests[0], "post_id")
    assert minted in str(exc.value)


def test_bearer_and_surface_on_all_requests(tmp_path):
    seen = []
    api = FakeDraftsAPI(pending_404s=1)
    inner = api.handler

    def spy(request):
        seen.append((request.url.path, request.headers.get("Authorization"),
                     request.headers.get("X-Client-Surface")))
        return inner(request)

    api.transport = lambda: httpx.MockTransport(spy)
    with _client(tmp_path, api) as client:
        analyze.upload_and_analyze(
            client, _video(tmp_path, 100), sleep=lambda s: None,
        )
    assert len(seen) == 3  # upload + two polls
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


# ── async split: upload / check_analysis / get_video_url ─────────────


def test_upload_returns_post_id_without_polling(tmp_path):
    api = FakeDraftsAPI()
    events = []
    with _client(tmp_path, api) as client:
        post_id = analyze.upload(client, _video(tmp_path, 100),
                                 on_event=events.append)
    assert post_id == _form_value(api.upload_requests[0], "post_id")
    import uuid

    assert uuid.UUID(post_id).version == 4  # minted client-side
    assert api.polls == 0  # upload alone never touches the poll endpoint
    assert len(api.upload_requests) == 1
    assert all(e["event"] == "upload_progress" for e in events)


def test_check_analysis_pending_returns_none(tmp_path):
    api = FakeDraftsAPI(pending_404s=1)
    with _client(tmp_path, api) as client:
        assert analyze.check_analysis(client, POST_ID) is None
        assert analyze.check_analysis(client, POST_ID) == ANALYSIS
    assert api.polls == 2


def test_check_analysis_failed_raises_terminal(tmp_path):
    api = FakeDraftsAPI(pending_404s=0)
    api.poll_result = {
        "post_id": POST_ID, "user_id": "u-1",
        "status": "failed", "failure_reason": "corrupt_video",
    }
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalysisFailed, match="corrupt_video"):
            analyze.check_analysis(client, POST_ID)


def test_check_analysis_http_error_raises(tmp_path):
    def handler(request):
        return httpx.Response(500)

    api = FakeDraftsAPI()
    api.transport = lambda: httpx.MockTransport(handler)
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalyzeError, match="HTTP 500"):
            analyze.check_analysis(client, POST_ID)


def test_poll_timeout_is_analysis_timeout_subclass(tmp_path):
    api = FakeDraftsAPI(pending_404s=10_000)
    with _client(tmp_path, api) as client:
        with pytest.raises(analyze.AnalysisTimeout) as exc:
            analyze.poll_analysis(
                client, POST_ID, sleep=lambda s: None, max_wait_seconds=30,
            )
    assert isinstance(exc.value, analyze.AnalyzeError)
    assert POST_ID in str(exc.value)


def _video_url_client(tmp_path, handler):
    api = FakeDraftsAPI()
    api.transport = lambda: httpx.MockTransport(handler)
    return _client(tmp_path, api)


def test_get_video_url_from_json_body(tmp_path):
    url = "https://cdn.example.test/signed.mp4?sig=abc"

    def handler(request):
        assert request.url.path == f"/api/v1/drafts/{POST_ID}/video"
        assert request.headers["Authorization"] == "Bearer at-1"
        return httpx.Response(200, json={"url": url})

    with _video_url_client(tmp_path, handler) as client:
        assert analyze.get_video_url(client, POST_ID) == url


def test_get_video_url_from_redirect(tmp_path):
    url = "https://cdn.example.test/signed.mp4?sig=abc"

    def handler(request):
        return httpx.Response(302, headers={"Location": url})

    with _video_url_client(tmp_path, handler) as client:
        assert analyze.get_video_url(client, POST_ID) == url


def test_get_video_url_404_is_actionable(tmp_path):
    def handler(request):
        return httpx.Response(404, json={"detail": "not found"})

    with _video_url_client(tmp_path, handler) as client:
        with pytest.raises(analyze.AnalyzeError, match="No stored video"):
            analyze.get_video_url(client, POST_ID)


def test_get_video_url_missing_url_in_body(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"something_else": True})

    with _video_url_client(tmp_path, handler) as client:
        with pytest.raises(analyze.AnalyzeError, match="did not include a video URL"):
            analyze.get_video_url(client, POST_ID)


# ── drafts listing ───────────────────────────────────────────────────


def test_list_videos_happy_path(tmp_path):
    rows = [{"post_id": "p-1"}, {"post_id": "p-2"}]
    seen = {}

    def handler(request):
        assert request.url.path == "/api/v1/drafts"
        assert request.headers["Authorization"] == "Bearer at-1"
        seen["limit"] = request.url.params.get("limit")
        return httpx.Response(200, json={"videos": rows})

    with _video_url_client(tmp_path, handler) as client:
        assert analyze.list_videos(client, limit=50) == rows
    assert seen["limit"] == "50"


def test_list_videos_bare_list_body(tmp_path):
    rows = [{"post_id": "p-1"}]

    def handler(request):
        return httpx.Response(200, json=rows)

    with _video_url_client(tmp_path, handler) as client:
        assert analyze.list_videos(client) == rows


def test_list_videos_403_raises_list_unauthorized(tmp_path):
    def handler(request):
        return httpx.Response(403, json={"detail": "Firebase session required"})

    with _video_url_client(tmp_path, handler) as client:
        with pytest.raises(analyze.ListUnauthorized, match="HTTP 403"):
            analyze.list_videos(client)


def test_list_videos_500_raises_analyze_error(tmp_path):
    def handler(request):
        return httpx.Response(500)

    with _video_url_client(tmp_path, handler) as client:
        with pytest.raises(analyze.AnalyzeError, match="HTTP 500"):
            analyze.list_videos(client)


def test_list_videos_unexpected_shape(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"weird": True})

    with _video_url_client(tmp_path, handler) as client:
        with pytest.raises(analyze.AnalyzeError, match="[Uu]nexpected"):
            analyze.list_videos(client)


# ── video download (signed URL + GCS hop) ────────────────────────────


def test_download_video_two_hops(tmp_path):
    signed = "https://storage.example.test/bucket/clip.mp4?sig=abc"

    def api_handler(request):
        assert request.url.path == f"/api/v1/drafts/{POST_ID}/video"
        return httpx.Response(200, json={"url": signed})

    def gcs_handler(request):
        # the signed URL is fetched WITHOUT the API bearer token
        assert "Authorization" not in request.headers
        assert str(request.url) == signed
        return httpx.Response(200, content=b"video-bytes")

    dest = tmp_path / "saved.mp4"
    with _video_url_client(tmp_path, api_handler) as client:
        out = analyze.download_video(
            client, POST_ID, dest,
            download_transport=httpx.MockTransport(gcs_handler),
        )
    assert out == dest
    assert dest.read_bytes() == b"video-bytes"


def test_download_video_gcs_error(tmp_path):
    def api_handler(request):
        return httpx.Response(200, json={"url": "https://gcs.test/x"})

    def gcs_handler(request):
        return httpx.Response(403)

    with _video_url_client(tmp_path, api_handler) as client:
        with pytest.raises(analyze.AnalyzeError, match="HTTP 403"):
            analyze.download_video(
                client, POST_ID, tmp_path / "x.mp4",
                download_transport=httpx.MockTransport(gcs_handler),
            )


# ── caption generation ───────────────────────────────────────────────


def test_generate_caption_posts_and_extracts(tmp_path):
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == f"/api/v1/drafts/{POST_ID}/generate-caption"
        return httpx.Response(200, json={"caption": "Cats rule. #cats"})

    with _video_url_client(tmp_path, handler) as client:
        assert analyze.generate_caption(client, POST_ID) == "Cats rule. #cats"


def test_generate_caption_404_actionable(tmp_path):
    def handler(request):
        return httpx.Response(404, json={"detail": "not found"})

    with _video_url_client(tmp_path, handler) as client:
        with pytest.raises(analyze.AnalyzeError, match="Caption generation"):
            analyze.generate_caption(client, POST_ID)


# ── artifact renderers ───────────────────────────────────────────────


def test_render_transcript_plain_text():
    text = analyze.render_transcript({
        "transcript_segments": [
            {"text": "Hello.", "start_time": 0.0},
            {"text": "World.", "start_time": 1.0},
        ],
    })
    assert text == "Hello.\nWorld."


def test_render_transcript_empty():
    assert "no transcript" in analyze.render_transcript({})


def test_render_overlays_time_coded():
    text = analyze.render_overlays({
        "text_overlay_segments": [
            {"text": "BIG", "start_time": 0.5, "end_time": 1.5},
            {"text": "NO TIMES"},
        ],
    })
    assert "[0.5-1.5] BIG" in text
    assert "NO TIMES" in text


def test_render_scenes_numbered():
    text = analyze.render_scenes({"scenes": [{"description": "Intro"},
                                             {"description": "Outro"}]})
    assert "1. Intro" in text
    assert "2. Outro" in text


# --- production payload shape (observed live 2026-07-20; smoke test) ---------

_PROD_SHAPE = {
    "status": "completed",
    "transcription": {
        "text": "Welcome to the smoke test.",
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 2.5, "text": "Welcome to the smoke test."},
        ],
    },
    "text_overlays": {
        "text": "00:00:00:100 12",
        "segments": [{"start": 0.0, "end": 11.0, "text": "00:00:00:100 12"}],
    },
    "scenes": [{"start": 0.0, "end": 3.0, "title": "Intro", "description": "x"}],
}


def test_transcript_segments_production_shape():
    segs = analyze.transcript_segments(_PROD_SHAPE)
    assert segs and segs[0]["text"] == "Welcome to the smoke test."
    assert "Welcome to the smoke test." in analyze.render_transcript(_PROD_SHAPE)


def test_transcript_falls_back_to_plain_text():
    plain = {"transcription": {"text": "just text"}}
    assert analyze.transcript_segments(plain) == [{"text": "just text"}]


def test_transcript_falls_back_to_summary_audio_transcript():
    summary_only = {"summary": {"audio_transcript": "from summary"}}
    assert analyze.transcript_segments(summary_only) == [{"text": "from summary"}]


def test_overlay_segments_production_shape():
    segs = analyze.overlay_segments(_PROD_SHAPE)
    assert segs and segs[0]["end"] == 11.0
