"""What a URL actually points at, decided before anything tries to read it.

A code host serves a *file viewer* page at a PDF's URL, so an HTML extractor
pointed at one cannot fail loudly: it returns the page chrome and stores that as
the document. Rewriting the viewer URL and checking what came back avoids it.
"""

import logging
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_PDF_MAGIC = b"%PDF-"

# Read enough to identify the payload without committing to downloading it.
_SNIFF_BYTES = 8192

_MAX_BYTES = 200 * 1024 * 1024

# Left to the article extractor. text/plain is here on purpose -- prose is often
# served that way.
_MARKUP_TYPES = frozenset(
    {"text/html", "application/xhtml+xml", "text/plain", "text/markdown", ""}
)

# Recognisable documents this endpoint cannot ingest. Naming them beats handing
# the bytes to an HTML parser and storing whatever falls out.
_UNINGESTIBLE_TYPES = {
    "application/epub+zip": "EPUB",
    "application/zip": "archive",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word document",
    "application/msword": "Word document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint file",
}


class UningestibleRemoteContent(Exception):
    """The URL resolved to a file this endpoint knowingly cannot ingest."""


class RemoteDocumentTooLarge(Exception):
    """The URL resolved to a file past the size ceiling."""


@dataclass(frozen=True)
class RemoteDocument:
    content: bytes
    format: str
    filename: str
    url: str


_GITHUB_BLOB = re.compile(r"^/([^/]+)/([^/]+)/blob/(.+)$")
_GITLAB_BLOB = re.compile(r"^(/.+?)/-/blob/(.+)$")


def canonical_source_url(url: str) -> str:
    """Rewrite a code host's file-viewer URL to the raw file it displays.

    Only patterns whose raw form is documented and stable; anything else is
    returned unchanged.
    """
    parts = urlparse(url)
    host = parts.netloc.lower()

    if host in ("github.com", "www.github.com"):
        m = _GITHUB_BLOB.match(parts.path)
        if m:
            owner, repo, rest = m.groups()
            return f"https://raw.githubusercontent.com/{owner}/{repo}/{rest}"

    if host in ("gitlab.com", "www.gitlab.com"):
        m = _GITLAB_BLOB.match(parts.path)
        if m:
            project, rest = m.groups()
            return f"https://{parts.netloc}{project}/-/raw/{rest}"

    return url


def _filename_for(url: str) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    return stem.strip() or "Downloaded document"


def _is_pdf(head: bytes, declared: str, url: str) -> bool:
    """Decide from the leading bytes; raise for a file type we knowingly refuse."""
    if head.startswith(_PDF_MAGIC) or declared == "application/pdf":
        return True

    label = _UNINGESTIBLE_TYPES.get(declared)
    if label is not None:
        raise UningestibleRemoteContent(
            f"That URL is a {label}, which cannot be added from a link. "
            "Download it and upload the file instead."
        )

    # Unrecognised: the article extractor reads pages this sniff cannot classify,
    # and reports an empty extraction clearly enough when it cannot.
    logger.info(
        "remote_source: %s declared %r and is not a PDF; treating it as a page", url, declared
    )
    return False


async def fetch_remote_document(url: str) -> RemoteDocument | None:
    """Fetch `url` if it is a document; return None if it is a page to extract.

    Raises UningestibleRemoteContent for a recognised file type this endpoint
    cannot handle, and RemoteDocumentTooLarge past the size ceiling. Transport
    failures propagate: returning None would send the article extractor after a
    URL already known to be unreachable.
    """
    target = canonical_source_url(url)
    if target != url:
        logger.info("remote_source: rewrote %s to its raw form %s", url, target)

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        async with client.stream("GET", target, headers={"User-Agent": _UA}) as resp:
            resp.raise_for_status()
            declared = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()

            if declared in _MARKUP_TYPES:
                return None

            # Hosts serve PDFs as octet-stream, so the magic bytes decide, not
            # the header. Read once: aiter_bytes() is not restartable, and a
            # second pass silently yields the payload twice.
            chunks: list[bytes] = []
            size = 0
            verdict: bool | None = None

            async for piece in resp.aiter_bytes():
                chunks.append(piece)
                size += len(piece)
                if verdict is None and size >= _SNIFF_BYTES:
                    verdict = _is_pdf(b"".join(chunks)[:_SNIFF_BYTES], declared, target)
                    if verdict is False:
                        return None
                if size > _MAX_BYTES:
                    raise RemoteDocumentTooLarge(
                        f"That file is larger than {_MAX_BYTES // (1024 * 1024)}MB. "
                        "Download it and upload the file instead."
                    )

            # Body shorter than the sniff window, so nothing decided it yet.
            if verdict is None and not _is_pdf(b"".join(chunks), declared, target):
                return None

    return RemoteDocument(
        content=b"".join(chunks),
        format="pdf",
        filename=_filename_for(target),
        url=target,
    )
