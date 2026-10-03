"""Name the network failure a person can act on, from the text a client raised.

Error text is all that crosses the boundary here: prefetch errors arrive as strings,
and Ollama's pull reports Go errors inside a JSON event. A certificate refusal once
read as "Could not reach the local model server" on a company laptop whose local
server was fine, so a caller that cannot place the failure says nothing rather
than guess.
"""

import re

from app import proxy_env

# Python's ssl/requests/httpx wording, then Go's (Ollama).
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "inspected",
        re.compile(
            r"CERTIFICATE_VERIFY_FAILED|self[- ]signed certificate|unable to get local issuer"
            r"|x509:|certificate signed by unknown authority",
            re.IGNORECASE,
        ),
    ),
    (
        "proxy",
        re.compile(r"ProxyError|proxyconnect|Proxy Authentication Required|\b407\b", re.I),
    ),
    (
        "dns",
        re.compile(
            r"NameResolutionError|getaddrinfo failed|Name or service not known"
            r"|nodename nor servname|Temporary failure in name resolution|no such host",
            re.IGNORECASE,
        ),
    ),
    (
        "cut",
        re.compile(
            r"\bEOF\b|UNEXPECTED_EOF|Connection reset|connection was forcibly closed"
            r"|RemoteDisconnected|ConnectionResetError|Connection aborted",
            re.IGNORECASE,
        ),
    ),
    (
        "refused",
        re.compile(r"Connection refused|ECONNREFUSED|actively refused", re.IGNORECASE),
    ),
    ("timeout", re.compile(r"timed out|Timeout|i/o timeout|deadline exceeded", re.I)),
)

_SENTENCES = {
    "inspected": (
        "Your network checks secure connections using a certificate this computer does "
        "not trust, so the connection was refused. Your IT team can allow it, or try from "
        "another network."
    ),
    "proxy": (
        "Your network's proxy server refused the connection. Your IT team can allow "
        "it, or try from another network."
    ),
    "dns": "This computer could not find the server. Check your internet connection.",
    "cut": (
        "The connection was cut off. A firewall, VPN or web filter on your network may "
        "be blocking it. Try again, or try from another network."
    ),
    "refused": (
        "The server refused the connection. A firewall or your network may be blocking "
        "it. Try again, or try from another network."
    ),
    "timeout": "The server did not answer in time. Check your internet connection and try again.",
}


# The one case the person can fix without IT changing the network: give the app a
# manual proxy, which both it and Ollama read at launch (#155).
PAC_ONLY = (
    "Your network sets its proxy with a setup script, which Luminary cannot use yet. "
    "Ask your IT team for the proxy server's address and port, enter them in Windows "
    "Settings > Network & internet > Proxy > Manual proxy setup, then restart Luminary."
)


def kind(text: str) -> str | None:
    """The failure class *text* describes, or None when it names none."""
    return next((name for name, pattern in _PATTERNS if pattern.search(text)), None)


def explain(text: str) -> str | None:
    """A sentence for the person reading the setup screen, or None."""
    found = kind(text)
    if found is None:
        return None
    # A certificate refusal is the proxy answering, so the script was not the problem.
    if found != "inspected" and proxy_env.pac_only():
        return PAC_ONLY
    return _SENTENCES[found]
