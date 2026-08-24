"""A user-supplied URL must never be able to become a yt-dlp option.

`create_subprocess_exec` rules out a shell, but not argv parsing: a value
beginning with "-" is read by the child as a flag, and yt-dlp's flags include
ones that read and write files. Today `is_youtube_url` blocks it by demanding an
https://youtube.com/... prefix, so the hole is closed incidentally -- one
loosened validator away from being open again.

`--` closes it structurally, which is the only way it stays closed.
"""

import inspect

from app.services import youtube_downloader


def _argv_before_url(source: str, marker: str) -> str:
    body = source.split(marker, 1)[1]
    return body.split("url,", 1)[0]


def test_metadata_fetch_ends_option_parsing_before_the_url():
    argv = _argv_before_url(inspect.getsource(youtube_downloader), "--dump-json")
    assert '"--"' in argv


def test_audio_download_ends_option_parsing_before_the_url():
    argv = _argv_before_url(inspect.getsource(youtube_downloader), '"-x"')
    assert '"--"' in argv


def test_a_url_that_looks_like_a_flag_is_still_rejected_upstream():
    """Defence in depth: the allowlist and the separator both have to hold."""
    assert not youtube_downloader.is_youtube_url("--config-location=/etc/passwd")
    assert not youtube_downloader.is_youtube_url("-o/tmp/pwned")
    assert youtube_downloader.is_youtube_url("https://www.youtube.com/watch?v=abc")
