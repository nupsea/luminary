# Releasing

How a code change reaches a user's Mac. Credentials setup is a separate,
one-time job — see `release-credentials.md`.

## The model

A pushed `v*` tag is the only trigger. Two workflows answer it and attach their
artifacts to the same GitHub release:

| Workflow | Runner | Produces | Time |
|---|---|---|---|
| `release.yml` | ubuntu | source tarball for `bootstrap.sh` / headless installs | ~20 min |
| `release-macos-app.yml` | macos-14 | signed, notarized `Luminary_<v>_aarch64.dmg` | 45–80 min |

Whichever finishes first creates the release; the other uploads into it. Order
does not matter.

**There is no auto-updater.** A new version reaches an existing user only when
they download the new DMG. Plan announcements accordingly — release notes are
the only channel.

## Shipping a new version

```bash
# 1. Everything green, working tree clean.
make ci

# 2. Bump the version. This writes all four places it lives:
#    backend/pyproject.toml, frontend/package.json,
#    src-tauri/tauri.conf.json, src-tauri/Cargo.toml
scripts/version.sh 0.3.0
scripts/version.sh            # confirm all four agree

# 3. Note what changed, for the release page.
$EDITOR CHANGELOG.md

git commit -am "release: 0.3.0"
git push

# 4. Tag. This is the trigger.
make release
```

`make release` refuses a dirty tree, tags `v<version>` from
`backend/pyproject.toml`, and pushes.

Then watch the run:

```bash
gh run watch
gh release view v0.3.0
```

The DMG must be present before you tell anyone. If notarization fails, the run
uploads `notary-logs` as an artifact — that is where the reason is.

## Building a DMG without releasing

For testing a change, or handing a build to someone directly:

```bash
make stage && make verify-stage      # payload, runtime, inference server
make desktop-app                     # unsigned .app

APP=src-tauri/target/release/bundle/macos/Luminary.app
bash scripts/macos/sign.sh          "$APP"          # or --adhoc, see below
bash scripts/macos/verify_signed.sh "$APP"
bash scripts/macos/dmg.sh           "$APP" 0.3.0
bash scripts/macos/notarize.sh build/dist/Luminary_0.3.0_aarch64.dmg "$APP"
```

`make desktop-adhoc` runs the same chain with the ad-hoc identity and no
credentials. It exercises every step and gate, but the result is **not**
distributable: Gatekeeper rejects ad-hoc signatures on any machine that did not
build them.

## What an update does to a user's data

Nothing is lost, and almost nothing is re-downloaded.

| | On update |
|---|---|
| Library, notes, documents, cards (`DATA_DIR`) | untouched |
| Downloaded models (~1.4 GB, plus any chat model) | untouched, not re-fetched |
| Installed components (`extras/`, `bin/`, `ollama/`) | untouched |
| The app bundle | replaced wholesale, ~700 MB |
| Database schema | migrated on next launch by Alembic |

The user drags the new `Luminary.app` over the old one. Everything under
`~/Library/Application Support/sh.luminary.app/` is theirs and survives.

**A newer library cannot be opened by an older build.** Startup only ever runs
`upgrade head`. Every revision does implement `downgrade`, but nothing invokes
it, so once a user has launched a release carrying a migration, going back
means the app refuses to start:

```
CommandError: Can't locate revision identified by '<newer revision>'
```

Recovering means running `alembic downgrade` by hand from the newer checkout,
and one existing revision drops tables outright — its own comment says to
export first. So in practice, treat any release carrying a migration as a
commitment: if it has to be pulled, users who already ran it move forward, not
back. Say so in the release notes.

## Before tagging

- `make ci` green.
- `scripts/version.sh` shows the same version in all four files.
- `CHANGELOG.md` updated.
- If the release carries an Alembic migration, say so in the notes — it is the
  point of no return described above.
- A DMG built and launched locally at least once, on a cleared
  `~/Library/Application Support/sh.luminary.app`, to confirm first-run setup
  still works.

## If a release is bad

Assets can be replaced in place; the tag stays.

```bash
gh release delete-asset v0.3.0 Luminary_0.3.0_aarch64.dmg
# fix, rebuild, then
gh release upload v0.3.0 build/dist/Luminary_0.3.0_aarch64.dmg --clobber
```

If the code itself is wrong, ship `0.3.1` rather than re-cutting `0.3.0` —
anyone who already downloaded it has no way to learn it was replaced.
