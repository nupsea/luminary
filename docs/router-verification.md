# Router verification

Client-side routing is the one layer the automated gates cannot see. `tsc
--noEmit` and the vitest suite both pass against a broken router, because the
component/hook API (`Link`, `NavLink`, `Navigate`, `useLocation`,
`useNavigate`, `useParams`, `useSearchParams`) type-checks identically across
react-router majors — what changes underneath is runtime behaviour: the history
stack, `location.state` propagation, and whether a `replace` keeps state.

`make verify-router` drives the live UI in a real Chromium and asserts that
behaviour. **Re-run it after any react-router upgrade.**

## Running it

```sh
make luminary        # in one shell; the script drives the running app
make verify-router   # in another
```

Overrides: `LUMINARY_URL` (default `http://localhost:5173`), `LUMINARY_API`
(default `http://localhost:7820`). Exits non-zero if any check fails.
Screenshots and `results.json` land in `frontend/.router-verify/` (gitignored).

`playwright-core` is installed with `--no-save` on first run, so it never
enters `package.json` and CI never pulls a browser. The script needs a running
app, so it is deliberately not part of `make ci`.

## What it asserts

| Area | Check |
| --- | --- |
| Tab rail | Every `nav a` destination navigates, sets `aria-current="page"`, and renders content |
| History | Back ×3 and Forward ×2 replay the exact expected stack, and the view re-renders |
| Deep links | A pasted document URL opens the reader; a pasted note URL loads the note; both survive a hard refresh |
| Unknown routes | Self-heal to `/` via the catch-all redirect |
| `location.state` | A hub card's `state: { from }` reaches `useBackNavigation()` as a labelled back button, and `navigate(-1)` returns to the origin |
| `setSearchParams` | The library's `?doc=` cleanup strips the param, preserves `state.from` through the `replace`, and adds no history entry |
| Mount integrity | The app root stays mounted across route and view-mode changes |
| Console | No react-router warnings |

Checks that depend on library content (a document, a note, an in-progress hub
card) report `SKIP` with the reason on an empty install rather than failing.

## Why the mount-integrity check exists

A render crash inside a route unmounts the entire React root: the URL stays
correct, the tab title stays correct, and the page is blank. Any assertion that
only compares URLs — or counts `body.innerText` characters, which the app shell
alone satisfies — passes straight through it. Assert on content owned by the
route (for CodeMirror surfaces, `.cm-content`) and on `#root` having children.

## Scope

The script exercises the dev server. Deep-link URL handling under `make start`
is served by `serve_spa` in `backend/app/main.py` — a static-file fallback that
no frontend dependency bump can affect.
