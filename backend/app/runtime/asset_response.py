"""Headers for serving a file whose bytes came from a user or an imported source.

Served on the app's own origin, an SVG opened directly runs its script there, and that
script's requests are the tokenless local principal (I-79). The sandbox gives such a
document an opaque origin and no script; an `<img>` ignores both headers, so pictures
render as before.
"""

UNTRUSTED_ASSET_HEADERS = {
    "Content-Security-Policy": (
        "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    ),
    "X-Content-Type-Options": "nosniff",
}
