"""yt-dlp failure reporting.

The download path discarded stderr, so a stale binary reported only
"exit 1" while yt-dlp was printing the actual cause.
"""

# yt-dlp's reason for failing is the actionable part


def test_last_error_line_surfaces_the_reason():
    """A discarded stderr is why a five-month-old yt-dlp pin went unnoticed.

    The user saw "yt-dlp download failed (exit 1)" and nothing else, while the
    binary was printing "HTTP Error 403: Forbidden" on every video.
    """
    from app.services.youtube_downloader import _last_error_line

    stale = (
        b"WARNING: [youtube] No supported JavaScript runtime could be found\n"
        b"ERROR: unable to download video data: HTTP Error 403: Forbidden\n"
    )
    assert "403: Forbidden" in _last_error_line(stale)
    # The last ERROR wins over earlier warnings.
    assert not _last_error_line(stale).startswith("WARNING")


def test_last_error_line_falls_back_and_stays_bounded():
    from app.services.youtube_downloader import _last_error_line

    assert _last_error_line(b"") == ""
    assert _last_error_line(None) == ""
    # No ERROR: line -- the last non-empty line still explains more than nothing.
    assert _last_error_line(b"odd failure\n") == "odd failure"
    # Bounded, so a wall of output cannot become a toast.
    assert len(_last_error_line(b"ERROR: " + b"x" * 5000)) <= 300


# How yt-dlp is started


def test_ytdlp_runs_as_a_module_of_this_interpreter(monkeypatch):
    """An installed Windows app has no working yt-dlp.exe to find.

    uv's launcher records the build machine's interpreter path inside the
    executable, so resolving the console script picked a file that could only
    fail. The module form runs the same package with no script involved.
    """
    from app.services import youtube_downloader

    monkeypatch.setattr(youtube_downloader, "resolve_tool", lambda _n: "/dead/launcher/yt-dlp")
    assert youtube_downloader._ytdlp_argv() == [youtube_downloader.sys.executable, "-m", "yt_dlp"]
    assert youtube_downloader.check_ytdlp_available()


def test_ytdlp_falls_back_to_a_tool_when_the_module_is_absent(monkeypatch):
    from app.services import youtube_downloader

    monkeypatch.setattr(youtube_downloader.importlib.util, "find_spec", lambda _n: None)
    monkeypatch.setattr(youtube_downloader, "resolve_tool", lambda _n: "/opt/tools/yt-dlp")
    assert youtube_downloader._ytdlp_argv() == ["/opt/tools/yt-dlp"]
    assert youtube_downloader.check_ytdlp_available()

    monkeypatch.setattr(youtube_downloader, "resolve_tool", lambda _n: None)
    assert not youtube_downloader.check_ytdlp_available()
