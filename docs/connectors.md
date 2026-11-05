# Connectors

A connector fetches a source into a **source bundle**; the core does everything after that. It
parses, chunks, embeds, cites and writes cards the same way for every document, so a connector
never decides what a citation points at. Why connectors are separate processes in other
repositories is in `docs/roadmap.md` §7. This file is the contract as built.

| Piece | Where |
|---|---|
| SDK (standard library only, Apache-2.0) | `packages/luminary-source-sdk/` |
| Protocol | `luminary_source_sdk/protocol.py` |
| Bundle format | `packages/luminary-source-sdk/schema/source-bundle.schema.json`, mirrored by `backend/app/schemas/source_bundle.py` |
| Runner | `backend/app/services/connector_runner.py` |
| Install, claim, credentials | `backend/app/services/connectors.py` |
| Catalogue | `backend/app/services/connector_catalogue.py` |
| Importer | `backend/app/services/source_bundle.py` (`store_bundle`, `parse_bundle`) |
| Conformance kit | `luminary_source_sdk/conformance.py` |
| Public connectors | [`nupsea/luminary-connectors`](https://github.com/nupsea/luminary-connectors): `youtube`, `html-book` |
| Template for a new connector | `luminary-connectors/template/`: fails only its placeholder terms until they are quoted |

## Process

One process per request, started as `python -I -m luminary_source_sdk.serve <module:Class>`
from the connector's own environment.

- **Request.** One JSON line on stdin, at most 1 MiB:
  `{"protocol": 1, "op", "input", "credentials", "dest"}`.
- **Answer.** Event lines on stdout: `progress` (`fraction` 0-1, `stage`), `log`, then exactly
  one `result` or `error` (`code`: `input`, `auth`, `source` or `internal`). `serve` moves the
  connector's own `print` to stderr, which the core logs.
- **Environment.** Only `PATH`, home and temp directories, locale, and proxy and CA settings
  (`_ENV_KEYS`). Never the backend's API keys.
- **Credentials.** Only in the request: never in argv, the environment or a file the connector
  reads. The core stores them owner-only in `<machine root>/connectors/<name>/credentials.json`.
- **Timeouts.** `fetch` 60 minutes; `describe`, `check` and `preview` 120 s. On a timeout the
  core kills the whole process group.

| Op | Returns | When |
|---|---|---|
| `describe` | `Description` | At install; stored as `connector.json` |
| `check` | `Account` (`valid`, `account`, `message`) | Before credentials are stored |
| `preview` | `Preview`: a title, a detail, and `Choice`s of `Option`s | `Description.preview` is true, before a fetch |
| `fetch` | `{"bundle": dest}` | Writes the bundle into `dest`, which must be empty |

## Description

Install refuses a connector whose `describe` breaks any of these rules
(`connectors._check_description`):

- `name` equals its `luminary.connectors` entry-point name: lowercase letters, digits and `-`,
  at most 64.
- `terms.statement` quotes what the source's own terms say about this use, and `terms.url` is
  https. Licence and terms are shown before install and copied into every bundle. The
  template's `PLACEHOLDER_TERMS` is refused, by install and by the kit.
- Each `url_prefixes` entry is a scheme, a host and a path (`https://doc.rust-lang.org/book/`).
  A pasted link goes to the first installed connector, by name, that claims it.
- `media` lists only `text`, `audio` and `youtube`; `tools` lists only `ffmpeg`. The core
  refuses a link before fetching when it cannot transcribe the media or find a tool. It passes
  each tool's path as `input["tools"][name]`.

`inputs` and `credentials` are `Field`s, which the app draws as a form; `secret` fields are
masked and `multiline` ones take a pasted block. `label` is the source's name in messages.

## Bundle

```
manifest.json
sections/<id>.html | <id>.md      one file per table-of-contents entry
assets/<name>                     images, cover, audio, caption tracks
```

The manifest requires `bundle_version` (1), `connector` (`name`, `version`), `title`, `media`
and `terms`. `sections` are in reading order, each with `id`, `heading`, `level`, `file` and an
optional `source_url`. Optional fields:

| Field | Becomes |
|---|---|
| `authors`, `cover`, `source_url`, `locator` | The document's metadata |
| `labels` | Library tags, applied as a user's own |
| `tags` | The source's subject tags; vocabulary only |
| `description`, `chapters` | A talk's description and chapter titles; prime transcription |

`media` is `{"kind": "text"}` (sections required) or an audio kind, `audio` or `youtube`, with
`audio` and optional `captions` asset paths. The core transcribes audio bundles.

**How the importer reads a text bundle.** Each HTML section is read the way an EPUB chapter is
(`parser.epub_chapter_sections`):
- Text before the section's first heading is dropped.
- Everything after it is kept, `<nav>`, footers and "edit this page" links included.

So a connector strips its source's chrome itself. A Markdown section is taken whole. A section
with under 50 characters of text (`MIN_SECTION_CHARS`) is skipped, and a bundle with no section
left is refused.

**Ceilings** (`source_bundle.py`; each names the cases that set it):

| Ceiling | Value |
|---|---|
| A section file | 4 MiB |
| All section text | 64 MiB |
| Sections | 5,000 |
| Files | 20,000 |
| Whole bundle | 2 GiB |

The importer copies the bundle entry by entry, refusing links, files outside `sections/` and
`assets/`, and section files that are not HTML or Markdown. It validates the copy, so nothing
the connector changes afterwards reaches the library. Re-import reads the stored copy and
never runs the connector again.

## Install

`install_from_folder` runs `uv sync` (`--locked` from the catalogue) in the connector's own
folder, into `<machine root>/connectors/<name>/env/`. The catalogue pins each entry to a GitHub
archive by sha256 and refuses a tampered archive before unpacking it. The connector's
dependencies never meet the core's.

## Conformance kit

Run it in the connector's environment against a source whose table of contents you wrote down
by reading the source itself:

```
uv run python -m luminary_source_sdk.conformance my_package:MySource truth.json \
    --luminary /path/to/luminary/backend
```

`truth.json` is `{"input": {...}, "toc": [...], "chrome": [...], "credentials": {...}}`. The
kit checks:
- the description as install would;
- that `fetch` ends in a result and its progress never goes backwards;
- that the connector's source imports no `app` module;
- that the manifest names the connector and carries its terms;
- each TOC entry found, nothing extra, in TOC order, with no empty section;
- no `chrome` string in any section.

`--luminary` also runs the bundle through the real importer (`app.scripts.check_bundle`) and
checks the chrome again on what it keeps. Never take the ground truth from the connector's own
output, or from a page the connector is not allowed to use as a shortcut: the check would
pass by construction.

## Catalogue review

A connector is listed in the catalogue only when every item holds:

1. **The source's terms are read and quoted.** `terms` states what they say about automated
   download and about use as model input, with the page's date. A source whose terms forbid
   the use is not listed. A connector that gets past a site's bot defence is never listed.
2. **The licence is decided.** The connector's own licence, and each dependency's, under the
   same policy as `scripts/licence_policy.json` (I-71).
3. **The conformance kit passes with `--luminary`,** on at least one test source per kind of
   source it claims, and the ground truth is committed beside its tests.
4. **No `app` import,** checked by the kit, and no dependency on Luminary beyond the SDK.
5. **Credentials only through the protocol.** Nothing read from the environment, argv, a
   browser profile or a file the user did not hand over in the sign-in form.
6. **A pinned archive.** The entry names a commit, the archive's sha256 and size, and a
   `uv.lock` that `uv sync --locked` accepts.

## Releasing the SDK

`luminary-source-sdk` is published to PyPI by `.github/workflows/release-sdk.yml`, through trusted
publishing: GitHub proves the workflow's identity to PyPI, so no token is stored.

- **Once, on PyPI:** add a pending publisher (pypi.org/manage/account/publishing) for project
  `luminary-source-sdk`, owner `nupsea`, repository `luminary`, workflow `release-sdk.yml`,
  environment `pypi`. In this repository, create the `pypi` environment. A required reviewer on it
  makes each release wait for approval.
- **Each release:** set `version` in `packages/luminary-source-sdk/pyproject.toml`, merge, then
  push the tag `sdk-v<version>` on master. The job refuses a tag that does not match the
  version. It checks that the wheel installs alone and carries its schema before publishing.

Until the first release, connectors pin the SDK by a GitHub archive of this repository.
