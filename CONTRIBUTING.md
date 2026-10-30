# Contributing to Luminary

Luminary has one maintainer. Writing a change is cheap now and reviewing one is not, so this
process spends review time only on changes that were agreed before they were written.

## The short version

1. **Start from an issue.** Pick one or open one, and comment with the approach you plan. Work
   starts when a maintainer adds the `accepted` label. A PR without an accepted issue may be
   closed unread.
2. **One issue, one small PR**, on a branch from `master`. CI refuses a branch whose name does not
   start with `feat/`, `fix/`, `docs/`, `chore/`, `refactor/`, `ci/`, `feature/`, `bugfix/` or
   `hotfix/`.
3. **AI tools are welcome.** Say which you used in the PR and read every line before you submit.
   You answer the review, not your agent.
4. **`make ci` green locally** before you ask for review.
5. **Sign off every commit** (`git commit -s`), certifying the [DCO](#developer-certificate-of-origin).
   CI checks it.

## Help that needs no code

These are what one maintainer cannot do alone.

| Contribution | How |
|---|---|
| Run Luminary on your hardware | Install a [release](https://github.com/nupsea/luminary/releases/latest) and file a **Hardware report**. Most wanted: Windows or Linux with an NVIDIA or AMD card, integrated graphics, 16 GB machines. Issues labelled `needs-hardware` are blocked on one |
| Break it with your own library | Ingest the books, papers and videos you actually read, and file a **Bug report** for anything wrong. A chapter split in the wrong place, or a citation that lands on the wrong passage, is a bug |
| Judge flashcards | Generate cards from a book you know well and say which you would keep and which are wrong against their passage. #330 describes the gate those judgements feed |

## Setup

You need `git`, `make`, `curl`, and a machine that can run a local model: Apple Silicon, or
Windows or Linux with an NVIDIA or AMD card, and at least 16 GB of memory (README, "What your
machine needs"). `make install-dev` installs uv, Node and Ollama if missing, and downloads
several GB of models on its first run.

```bash
git clone https://github.com/YOUR-USERNAME/luminary.git   # your fork
cd luminary
make install-dev
make dev          # backend on :7820 with reload, frontend on :5173
```

| Command | Does |
|---|---|
| `make ci` | Everything CI runs: ruff, the layer and boundary linters, the quality ratchet, pytest and vitest with coverage floors, the frontend build, tsc, eslint, knip |
| `make lint` | The quick subset: ruff, tsc, eslint, knip, manifest checks |
| `make test` | pytest |
| `make smoke` | HTTP contract scripts against a running backend. Run it when you change an endpoint |
| `make clean` | Free ports 7820, 5173 and 5174 |
| `make uninstall` | Remove what `make install-dev` added; `ARGS=--dry-run` lists it first |

A green `make ci` on your machine is necessary but not sufficient: GitHub runs it again on the PR,
and memory pressure there has failed runs that passed locally.

## Working with an AI coding agent

The repository is written to be worked on by agents. Point yours at these before it writes code:

| File | What it gives the agent |
|---|---|
| `CLAUDE.md` (`AGENTS.md` points to it) | The entry point: a table of contents into `docs/`, the commands, and the rules agents break most |
| `docs/invariants.md` | Rules that each came from a shipped bug, most naming the test that guards them. Have the agent read it in full before a backend change |
| `.claude/skills/*/SKILL.md` | Procedures for an endpoint, a schema migration, a retrieval change, an eval and a frontend surface. Claude Code loads them itself; with other tools, name the one that fits |
| `.claude/rules/common/` | How comments, commits and claims of "done" are written here |

An agent reporting that it is done has not run `make ci` until you have seen the output. Before
you submit, check the diff for what agents here most often get wrong:

- Changes outside the issue, such as a refactor "while I was there".
- Comments narrating the work. Comments here are a one- or two-line why
  (`.claude/rules/common/clean-code.md`).
- A test or check that passes on a value the code supplies itself, such as a default, placeholder
  or prompt example (`.claude/rules/common/product-integrity.md`).
- A PR description that restates the diff instead of saying why and how it was checked.

## Rules a change must follow

The full set is `docs/architecture.md` and `docs/invariants.md`. These are the ones broken most:

- Imports go one way: Types → Config → Repo → Service → Runtime → API (`tools/layer_linter.py`).
- Every LLM call goes through LiteLLM, never a provider SDK.
- Services and repos raise `LuminaryError` subclasses, never `HTTPException`.
- Python packages are added with `uv add`, never pip or poetry.
- Read a dependency's licence before adding it. `make ci` fails on a shipped package whose licence
  `scripts/licence_policy.json` has not decided; copyleft needs an exception the maintainer grants
  (I-71).
- A new endpoint gets a pytest test and a `surface-manifest.json` entry (`add-endpoint` skill).
- A schema change edits `backend/app/models.py` and runs `make db-revision m="…"`, never raw
  `alembic revision`. Read the generated revision for drops you did not intend (I-23,
  `alembic-migration` skill).
- An eval change follows `evals/README.md` and the `eval-integrity` skill.
- A UI change includes a screenshot or a short recording in the PR.

## Trusted contributors

After a few merged PRs, a contributor may be invited as a collaborator: they can triage issues,
add `accepted`, and review other PRs. Trust goes to a person, and is withdrawn if their PRs stop
being read before they are submitted.

## Developer Certificate of Origin

Signing off a commit certifies the [Developer Certificate of Origin 1.1](https://developercertificate.org/):
you wrote the change, or otherwise have the right to submit it under the project's license
(Apache 2.0). That includes code an AI tool wrote for you. If an employer may own code you write,
check with them first.

`git commit -s` adds `Signed-off-by: Name <email>`; the email must match the commit's author. To
sign off commits already on a branch, run `git rebase --signoff master` and force-push.

## Reporting

- Bugs, features and hardware reports: [open an issue](https://github.com/nupsea/luminary/issues/new/choose)
  from a template. Search existing issues first.
- Questions: open a blank issue.
- Security: privately, as [SECURITY.md](SECURITY.md) describes. Never in a public issue.

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
