# Security — Luminary

## Security Boundaries

- **All data stays local**: Documents, embeddings, graph data, and flashcards are stored in DATA_DIR (`~/.luminary`). No data is sent to external services unless the user explicitly configures cloud LLM API keys.
- **API keys**: Stored in the SQLite `settings` table (plaintext v1). OS keychain integration is planned for v2.
- **No telemetry**: No usage data or telemetry is sent to Anthropic, OpenAI, or any third party unless the user has configured a cloud LLM key and explicitly initiates a request.
- **Cloud LLM opt-in**: Cloud providers (OpenAI, Anthropic, Google Gemini) are used only when `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY` is configured AND the user selects "cloud" mode in the UI.

## Data Handling

- Raw documents are stored in `DATA_DIR/raw/`
- Vector embeddings in `DATA_DIR/vectors/` (LanceDB)
- SQLite database at `DATA_DIR/luminary.db`
- Graph database at `DATA_DIR/graph.kuzu`
- All files are readable/writable only by the owning OS user

## API Security (v1 — local only)

- The FastAPI server binds to `127.0.0.1:8000` by default (not 0.0.0.0)
- CORS allows only `localhost:5173` (Vite dev) and `localhost:1420` (Tauri)
- No authentication required in v1 (single-user local app)
- Authentication to be added if multi-user or remote-access is ever supported

## Known Limitations (v1)

- API keys stored in plaintext in SQLite — acceptable for local use, not for shared systems
- No input sanitization beyond Pydantic validation at API boundary
- File upload does not scan for malware — user is responsible for trusted documents
