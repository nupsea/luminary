# Privacy-First Anonymous Telemetry

Luminary collects minimal, strictly anonymous install and usage telemetry. It features a built-in backend event store and optional forwarding to [TelemetryDeck v2](https://telemetrydeck.com/).

> [!NOTE]
> **No TelemetryDeck Account Required**: Luminary works out of the box without requiring a TelemetryDeck App ID. All installation and platform run metrics are logged and aggregated in the local Luminary backend (`.luminary/.telemetry_stats.json`). If you register an App ID on TelemetryDeck later, you can optionally plug it into Settings or set `LUMINARY_TELEMETRY_APP_ID` to sync with your TelemetryDeck dashboard.

## Why Telemetry?

As an open-source, local-first application supporting macOS (.dmg downloads and bootstrap installs), Windows (PowerShell installer), Linux/WSL (source install), and Docker, telemetry helps maintainers answer questions like:
- Which platforms and operating systems are people installing Luminary on?
- Do install scripts complete successfully or fail during setup?
- How many users run containerized Docker versions vs. native macOS or Windows?
- How many macOS `.dmg` downloads occur over time?

This allows the team to prioritize maintenance, catch platform-specific installation breakages early, and allocate resources effectively.

---

## Private mode sends nothing

**Telemetry is refused outright whenever the LLM mode is `private`**, ahead of every
other setting including an explicit opt-in. The README promises that private mode never
sends anything off the machine, and a user who chose it chose it for that reason.

Two consequences worth knowing:

- **`private` is the default mode**, so out of the box this feature records locally and
  transmits nothing. It reports only for users who have moved to hybrid or cloud.
- `settings_service.get_llm_mode()` defaults to `private`, so a settings cache that has
  not loaded yet fails closed rather than open.

Guarded by `test_private_mode_refuses_telemetry` and
`test_private_mode_is_the_failure_default`.

## Where to see it

Monitoring -> **Telemetry** (`/monitoring#telemetry`). The page is part of the
`monitoring` surface, which is `mode: full` in `surface-manifest.json`, so it never
ships on a public build.

It renders the captured fields **from the payload itself** rather than from a list
written in the page, so the disclosure cannot drift from what is actually sent. It also
shows the anonymous id, whether anything leaves the machine at all, and the events
recorded locally.

---

## Strict Privacy Guarantees

Luminary adheres to strict privacy-by-design standards:

1. **Zero Personal Data (No PII)**:
   - Luminary **never** collects usernames, machine hostnames, MAC addresses, or IP addresses.
   - Any local paths are automatically scrubbed (e.g., `/Users/john/...` is sanitized to `~/...`).

2. **No Content or Knowledge Exposure**:
   - **Zero** document titles, files, book passages, notes, flashcards, queries, prompts, or model completions are ever transmitted.

3. **Pseudonymized Client ID**:
   - Telemetry uses a randomly generated UUID v4 stored locally in `.luminary/.telemetry_id`.
   - It is never tied to hardware serial numbers, network addresses, or user identity.

4. **Non-Blocking & Offline Resilient**:
   - All telemetry requests run asynchronously in the background with a 2-second timeout.
   - If offline, firewalled, or if an endpoint is unreachable, requests are silently dropped without affecting installation or app performance.

---

## Opting Out

We respect your right to disable telemetry entirely. You can opt out at any time through any of the following methods:

### Method 1: Environment Variables (Installers & Terminal)
Set any of the standard environment variables before running install scripts or launching the server:

```bash
export DO_NOT_TRACK=1
# or
export LUMINARY_TELEMETRY=0
# or
export LUMINARY_TELEMETRY_DISABLED=1
```

On Windows PowerShell:
```powershell
$env:DO_NOT_TRACK = "1"
# or
$env:LUMINARY_TELEMETRY = "0"
```

In Docker / `docker-compose.yml`:
```yaml
environment:
  - DO_NOT_TRACK=1
```

### Method 2: In-App Settings UI
Open the **Settings** drawer in the Luminary web or desktop interface, scroll to **Anonymous Telemetry**, and toggle off **Share anonymous insights**.

---

## What Is Sent

When enabled, Luminary emits only high-level platform signals:

| Signal | Trigger | Example Payload |
|---|---|---|
| `install.linux.started` | `scripts/install.sh` starts | `{ "os": "Linux", "arch": "x86_64", "distro": "ubuntu_24.04", "status": "started" }` |
| `install.linux.completed` | `scripts/install.sh` finishes | `{ "os": "Linux", "arch": "x86_64", "duration_seconds": 185, "status": "success" }` |
| `install.windows.started` | `scripts/install.ps1` starts | `{ "os": "Windows", "arch": "x64", "powershell_version": "7.4.1", "status": "started" }` |
| `install.windows.completed` | `scripts/install.ps1` finishes | `{ "os": "Windows", "arch": "x64", "duration_seconds": 210, "status": "success" }` |
| `install.macos_bootstrap.started` | `scripts/bootstrap.sh` starts | `{ "os": "macOS", "arch": "arm64", "version": "0.8.28", "status": "started" }` |
| `install.macos_bootstrap.completed` | `scripts/bootstrap.sh` finishes | `{ "os": "macOS", "arch": "arm64", "duration_seconds": 312, "status": "success" }` |
| `install.first_run` | First launch of Luminary backend | `{ "distribution": "macos_dmg" \| "docker" \| "windows_native" \| "linux_source", "arch": "arm64" }` |
| `app.start` | Application server startup | `{ "luminary_version": "0.8.28", "distribution": "macos_dmg", "python_version": "3.13.0" }` |
| `metrics.github_dmg_downloads` | Sync of GitHub release download counts | `{ "floatValue": 450 }` |
