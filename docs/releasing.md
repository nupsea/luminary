# Releasing

How a code change reaches a user's Mac. Credentials setup is a separate,
one-time job — see `releasing.md`.

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

### When notarization stalls

Apple's queue can sit `In Progress` for hours without any acknowledgement on the
developer system status page, and submissions cannot be cancelled. Check whether
it is you or the service:

```bash
xcrun notarytool history --key "$APPLE_API_KEY_PATH" \
  --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER"
```

If recent submissions are all `In Progress` while older ones were accepted, the
service is behind — resubmitting will not jump the queue and only adds load.
Wait for one to resolve, then **re-run the `notarize` job alone** from the run
page. The build job's signed bundle is kept as the `signed-app` artifact for
seven days, so a retry skips the ~25 minute rebuild entirely.

## Building a DMG without releasing

For testing a change, or handing a build to someone directly:

```bash
make stage && make verify-stage      # payload, runtime, inference server
make desktop-app                     # unsigned .app

APP=src-tauri/target/release/bundle/macos/Luminary.app
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml | head -1)
bash scripts/macos/sign.sh          "$APP"          # or --adhoc, see below
bash scripts/macos/verify_signed.sh "$APP"
bash scripts/macos/notarize.sh      "$APP"          # before packaging
bash scripts/macos/dmg.sh           "$APP" "$VERSION"
bash scripts/macos/notarize.sh      "build/dist/Luminary_${VERSION}_aarch64.dmg"
```

`make desktop-adhoc` runs the same chain with the ad-hoc identity and no
credentials. It exercises every step and gate, but the result is **not**
distributable: Gatekeeper rejects ad-hoc signatures on any machine that did not
build them.

## Testing a rebuilt DMG

**Unmount the previous one first.** A mounted disk image keeps serving the inode
it opened, so rebuilding a DMG at the same path leaves `/Volumes/Luminary`
showing the old contents indefinitely — and anything dragged to `/Applications`
from that stale mount is old too, with nothing to indicate it.

```bash
hdiutil detach /Volumes/Luminary
open build/dist/Luminary_<version>_aarch64.dmg
```

Confirm what you are actually running before drawing conclusions from it:

```bash
ls /Applications/Luminary.app/Contents/Resources/backend/app/services/model_prefetch.py
```

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

---

## Credentials

What to obtain before a signed, notarized build is possible, and where each
piece goes. One-time setup, apart from the certificate's annual renewal.

Everything here is Apple's, and its only job is making macOS trust a downloaded
app. Luminary has no auto-updater, so no signing key of our own is involved.

### 1. Apple Developer Program

Enrol at <https://developer.apple.com/programs/>. $99/year, Apple ID with
two-factor required. Approval is usually same-day but can take longer for
organizations.

### 2. Developer ID Application certificate

Xcode is not required; the certificate can be requested with Keychain Access.

1. **Keychain Access → Certificate Assistant → Request a Certificate From a
   Certificate Authority.** Enter your email and name, select **Saved to disk**
   and **Let me specify key pair information**. Choose 2048 bits / RSA. This
   writes `CertificateSigningRequest.certSigningRequest`.
2. At <https://developer.apple.com/account/resources/certificates> choose **+**,
   then **Developer ID Application** (not "Mac Development" and not "Developer
   ID Installer"). Upload the CSR and download the resulting `.cer`.
3. Double-click the `.cer` to add it to your login keychain.
4. Confirm it is usable:

   ```bash
   security find-identity -v -p codesigning
   # Developer ID Application: Your Name (ABCDE12345)
   ```

   The 10-character suffix is your **Team ID**.

5. Export for CI: in Keychain Access select the certificate *and* its private
   key, **File → Export Items**, save as `.p12`, and set a password. That
   password becomes `APPLE_CERTIFICATE_PASSWORD`.

### 3. App Store Connect API key

Used by `notarytool`. It must be a **Team key** — personal keys are rejected by
the Notary API.

1. <https://appstoreconnect.apple.com> → **Users and Access** → **Integrations**
   → **App Store Connect API** → **Team Keys**.
2. **+**, name it, set access to **Developer**, generate.
3. Download `AuthKey_XXXXXXXXXX.p8`. **This download is offered once.** Store it
   somewhere durable, e.g. `~/private_keys/`.
4. Record the **Key ID** (in the filename and the table) and the **Issuer ID**
   (shown above the key list, a UUID).

### 4. Not needed yet: the updater key

Luminary ships as a downloaded DMG with no auto-updater, so nothing here
requires a Tauri signing key.

If you add one later, generate it once with
`node_modules/.bin/tauri signer generate -w ~/.tauri/luminary.key`, commit the
public key to `tauri.conf.json`, and keep the private key as a CI secret.
**Back it up**: losing it means no installed copy can ever be updated, since a
new key is a new identity that shipped copies will reject.

### 5. Test locally before touching CI

Faster feedback than a workflow run, and it uses the same scripts.

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (ABCDE12345)"
export APPLE_TEAM_ID=ABCDE12345
export APPLE_API_KEY_PATH=~/private_keys/AuthKey_XXXXXXXXXX.p8
export APPLE_API_KEY_ID=XXXXXXXXXX
export APPLE_API_ISSUER=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
APP=src-tauri/target/release/bundle/macos/Luminary.app
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml | head -1)

make stage
make desktop-app
bash scripts/macos/sign.sh          "$APP"
bash scripts/macos/verify_signed.sh "$APP"
bash scripts/macos/notarize.sh      "$APP"
bash scripts/macos/dmg.sh           "$APP" "$VERSION"
bash scripts/macos/notarize.sh      "build/dist/Luminary_${VERSION}_aarch64.dmg"
```

Two submissions, and each takes 10-30 minutes when the service is healthy; it
scales with file count and this bundle holds ~55k files. A ticket only attaches
to the artifact that was submitted, so the app is notarized and stapled before
`dmg.sh` packages it -- otherwise a copy dragged to `/Applications` carries no
ticket and its first launch needs a network round trip. The DMG is then
notarized so the download itself validates. On rejection,
`build/dist/notary-log-<artifact>.json` names the offending path.

Apple's queue can stall for hours without appearing on the developer system
status page; submissions cannot be cancelled. `xcrun notarytool history` shows
whether yours is `In Progress` or the service is simply behind.

The end state to check:

```bash
spctl --assess --type exec --verbose=4 "$APP"
# ...: accepted
# source=Notarized Developer ID
```

### 6. Provision CI

```bash
base64 -i /path/to/cert.p12                 | gh secret set APPLE_CERTIFICATE
base64 -i ~/private_keys/AuthKey_XXX.p8     | gh secret set APPLE_API_KEY
gh secret set APPLE_CERTIFICATE_PASSWORD
gh secret set APPLE_SIGNING_IDENTITY
gh secret set APPLE_TEAM_ID
gh secret set APPLE_API_KEY_ID
gh secret set APPLE_API_ISSUER
gh secret set KEYCHAIN_PASSWORD                 # any random string
```

Then tag a release; `.github/workflows/release-macos-app.yml` does the rest.

### Renewal

Apple issues Developer ID certificates for a term of up to five years, but a
much shorter one is possible. Read the expiry off the certificate rather than
assuming it:

```bash
security find-certificate -c "Developer ID Application" -p login.keychain \
  | openssl x509 -noout -enddate
```

Renewing means a new certificate, so `APPLE_CERTIFICATE` and
`APPLE_CERTIFICATE_PASSWORD` must be re-exported and re-set.

The Apple Developer Program membership renews annually. An expired membership
does not invalidate already notarized builds, but no new ones can be produced
until it is renewed.

---

## Demo assets


The README's hero is a GIF, not a video. GitHub strips `<video>` tags from
Markdown and sanitizes animated SVG, so an animated GIF referenced with a normal
image tag is the only thing that reliably plays on the front page. A linked
YouTube tour sits underneath it for anyone who wants more.

### Before recording anything

The library on screen is the product's first impression, and the previous
screenshots shipped with three documents reading `Enrichment failed`, several at
`0 words`, and the same YouTube video listed three times.

- [ ] Every document `stage=complete`, no failure badges, no `0 words` rows.
- [ ] No duplicate titles.
- [ ] Rename filename-shaped titles — `audit_unseen_arxiv_2508.03858` and
      `Chess2405.16755v1` read as debris next to `Attention` and `moby-dick`.
- [ ] Decide what is in frame. The library is personal; anything in it is
      published.
- [ ] Light theme, default zoom, window at 1440×900. Larger windows produce a
      GIF whose text is unreadable once GitHub scales it into the README column.
- [ ] Hide the OS menu bar clock and any notification that could fire mid-take.

Check the first two from the API rather than by eye:

```bash
curl -s "http://localhost:7820/documents?limit=200" | python3 -c "
import sys,json,collections
items=json.load(sys.stdin).get('items',[])
print('stages:', dict(collections.Counter(i['stage'] for i in items)))
print('zero-word:', sum(1 for i in items if not i.get('word_count')))
titles=[i['title'] for i in items]
print('duplicates:', [t for t,n in collections.Counter(titles).items() if n>1])
"
```

### Hero: "it keeps working with the wifi off"

Roughly 12 seconds. It proves the one claim competitors cannot copy, needs no
narration, and survives being watched with sound off in a README column.

| Beat | Seconds | On screen |
|---|---|---|
| 1 | 0.0–1.5 | Ask tab, a document already in scope. Cursor moves to the macOS menu bar. |
| 2 | 1.5–3.0 | Wi-Fi menu opens, **Wi-Fi switched off**. The menu-bar icon visibly changes. Hold one beat on the off state. |
| 3 | 3.0–4.5 | Type a real question about the document. Keep it short enough to finish in a beat. |
| 4 | 4.5–9.0 | The answer **streams in**. Do not cut this — streaming tokens are what makes it read as live rather than staged. |
| 5 | 9.0–11.0 | Click a citation chip. The reader opens on the passage; the chip shows its section and page. |
| 6 | 11.0–12.0 | Hold on the source with the wifi icon still off in frame. Freeze. |

Two things make or break it. **The wifi icon must stay visible in every frame** —
crop to include the menu bar, or the whole point is unproven. And **beat 5 needs
the citation fix** (`fix/citation-section-and-page`): before it, chips render
with no section and `page 0`, which undersells exactly what the shot exists to
show.

Suggested question, because the answer is short and the document is recognisable:
against `Attention`, ask *"What problem does multi-head attention solve?"*

### Later shots, in priority order

Each is a separate short GIF, placed next to the section it illustrates rather
than at the top.

1. **The receipt.** Ask → answer → click citation → reader opens on the exact
   passage, section and page on the chip. Illustrates "every answer shows its
   receipts". ~10s.
2. **Do you actually know it?** Card appears → predict *Know it* → flip → wrong →
   the calibration graph moves. Nobody else measures whether your self-assessment
   is honest. ~12s.
3. **One source, four surfaces.** Paste a YouTube URL → transcript, summary,
   flashcards and search results appear. Shows ingest breadth. ~15s, needs a
   speed-up over the ingestion wait.
4. **A card that admits it.** A deck showing `verified` next to `unverifiable`.
   The strongest honesty shot and the riskiest — it shows the product declining
   to certify, which reads as a feature only with a caption.

### Producing the file

Record with QuickTime (File → New Screen Recording), stop, save. Then one
command:

```bash
scripts/make_gif.sh ~/Desktop/raw.mov offline
```

It writes `assets/images/offline.gif` and prints the Markdown to paste. Needs
`ffmpeg` (`brew install ffmpeg`).

Trim and tune with environment variables rather than re-recording:

```bash
START=2.5 DURATION=12 scripts/make_gif.sh ~/Desktop/raw.mov offline   # cut the lead-in
FPS=10 WIDTH=800      scripts/make_gif.sh ~/Desktop/raw.mov offline   # smaller file
```

| Variable | Default | Why |
|---|---|---|
| `FPS` | 12 | Enough for UI motion; roughly half the size of 24 |
| `WIDTH` | 900 | The README column. Wider is unreadable once GitHub scales it |
| `START` / `DURATION` | whole clip | Trim without re-recording |
| `MAX_MB` | 5 | Warn above this |

The script builds the palette from the clip's own frames rather than using
ffmpeg's default. A global palette banks colours the UI never uses and renders
small text mushy, which is the usual reason a UI GIF looks worse than the
recording.

Target 2–3 MB. Over 5 MB the script tells you and lists what to try, in order:
cut a beat, drop to 10 fps, then narrow to 800 px. **Do not cut the beat where
the answer streams in** — a GIF that jumps to a finished answer reads as staged.

### Keeping them honest

A demo asset is a claim about the product, and the same rule applies to it as to
a number: it must show what the product actually does on the day it ships.

- Re-record when the surface in the shot changes. A GIF of a superseded layout is
  worse than no GIF, because it is indistinguishable from the current one.
- Never speed up a model response to look faster than it is. Speeding up an
  *ingestion wait* is fine and should carry an on-screen label.
- The library in frame is real. Do not stage a document the product never
  ingested.
