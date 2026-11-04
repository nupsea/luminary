# luminary-source-sdk

Write a connector: a small program that fetches content from one source into a Luminary
**source bundle**. Luminary does everything after the fetch, so a connector never decides what
a citation points at.

Standard library only, Apache-2.0.

## A connector

```python
from luminary_source_sdk import Connector, Description, Terms

TERMS = Terms(statement="What the source's own terms page says about this use.",
              url="https://example.com/terms")

class Example(Connector):
    def describe(self):
        return Description(name="example", version="0.1.0", licence="Apache-2.0", terms=TERMS,
                           url_prefixes=["https://example.com/docs/"])

    def fetch(self, input, credentials, bundle, report):
        bundle.add_section("intro", "Introduction", html="<h1>Introduction</h1><p>...</p>")
        report(1.0, "downloading")
        bundle.finish(connector=("example", "0.1.0"), title="Example docs", terms=TERMS,
                      source_url=input["url"])
```

A connector that writes audio declares it, and names any host tool it runs:

```python
Description(..., label="Example talks", media=["youtube"], tools=["ffmpeg"])
```

Luminary checks before a fetch that it can transcribe what the connector writes and that it
has each tool, so a link is refused with what to install rather than after a long download.
It passes each tool's path in the fetch input as `input["tools"]["ffmpeg"]`, since the bundled
app's `PATH` may not reach it. `bundle.add_asset_file(name, path)` moves a large file into the
bundle without reading it into memory; an audio bundle's manifest carries
`media: {"kind": "youtube", "url", "audio", "captions"}`, and its `description` and `chapters`
prime the transcript's vocabulary.

Name it in the connector's `pyproject.toml`:

```toml
[project]
dependencies = ["luminary-source-sdk"]

[project.entry-points."luminary.connectors"]
example = "example_connector:Example"
```

Until the SDK is on PyPI, depend on it from the Luminary repository:

```toml
[tool.uv.sources]
luminary-source-sdk = { git = "https://github.com/nupsea/luminary", subdirectory = "packages/luminary-source-sdk" }
```

## How Luminary runs it

One process per request, `python -I -m luminary_source_sdk.serve <entry point>`. The protocol
is in `protocol.py`: one request line on stdin, event lines on stdout. Credentials arrive only
in the request, the environment is cut down to what a network fetch needs, and anything the
connector prints goes to stderr, which Luminary logs. A fetch writes only into the directory
Luminary names, and Luminary validates the bundle again when it stores it:
`schema/source-bundle.schema.json` is the format.

`luminary_source_sdk.testing.run(entry, op, ...)` runs a request in-process, the same way, for
a connector's own tests.

## Terms

`describe` must state what the source's own terms say and where. Luminary shows it before the
connector is installed and stores it in every bundle. This SDK's licence covers its code, not
any source's terms.
