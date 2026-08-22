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
