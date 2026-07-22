# 💡 Suggested Issues for Contributors

These issues represent exciting problems, enhancements, and bugs for the Luminary project. Maintainers can copy-paste these descriptions directly into the GitHub Issue tracker to open them for community contributions.

---

## 1. 🟢 [Good First Issue][Frontend]: Keyboard Shortcuts for Spaced Repetition Review
* **Difficulty**: `difficulty/good-first-issue`
* **Area**: `area/frontend`
* **Target Files**:
  * [FlashcardManager.tsx](file:///Users/sethurama/DEV/LM/learning-mate/frontend/src/pages/Study/FlashcardManager.tsx)
  * [FlashcardCard.tsx](file:///Users/sethurama/DEV/LM/learning-mate/frontend/src/pages/Study/FlashcardCard.tsx)

### Problem Statement
Currently, during flashcard review sessions, users are forced to click buttons using their mouse or trackpad: first to click **"Show Answer"** to flip the card, and then to select their confidence/stability ratings: **"Blank"**, **"Unsure"**, or **"Know it"**. When reviewing dozens of cards, this mouse-heavy workflow is slow and tiring.

### Proposed Solution
Add global keyboard event listeners that listen for keypresses when a study session is active:
1. **Faced Down**:
   * `Space` or `Enter` should trigger **"Show Answer"** (flip the card).
2. **Faced Up**:
   * `1` (or `ArrowLeft` / `B`) should trigger the **"Blank"** grade.
   * `2` (or `ArrowDown` / `U`) should trigger the **"Unsure"** grade.
   * `3` (or `ArrowRight` / `K`) should trigger the **"Know it"** grade.

### Implementation Guidelines
* Use a React `useEffect` in `FlashcardManager.tsx` to bind the keydown event.
* **Important**: Ensure the event listener does not fire if the user is currently typing in a text input or note editor. You can check `document.activeElement.tagName` (e.g. ignore if active element is `INPUT`, `TEXTAREA`, or has `contenteditable`).
* Properly clean up the event listener on unmount.

---

## 2. 🟡 [Medium][Frontend]: Invert PDF colors in Dark Mode
* **Difficulty**: `difficulty/medium`
* **Area**: `area/frontend`
* **Target Files**:
  * [PDFViewer.tsx](file:///Users/sethurama/DEV/LM/learning-mate/frontend/src/components/reader/PDFViewer.tsx)

### Problem Statement
Luminary has a sleek dark theme. However, when a user opens a PDF textbook, the PDF pages themselves render with a bright white background. This is jarring and causes eye strain in low-light environments.

### Proposed Solution
Provide an option to invert the PDF page colors in dark mode:
1. Add an **"Invert Colors"** toggle button (with a sun/moon or contrast icon) in the PDF viewer toolbar.
2. When the app is in **dark mode** and the invert toggle is **enabled**, apply a CSS filter class to the PDF page container:
   ```css
   filter: invert(1) hue-rotate(180deg);
   ```
   *(The `hue-rotate(180deg)` keeps non-monochrome colors from changing their hue completely, which helps diagrams remain readable).*
3. Ensure settings are saved to `localStorage` so the preference persists.

---

## 3. 🟡 [Medium][Backend]: Check Ollama Reachability on Server Startup
* **Difficulty**: `difficulty/medium`
* **Area**: `area/backend`
* **Target Files**:
  * [main.py](file:///Users/sethurama/DEV/LM/learning-mate/backend/app/main.py)
  * [config.py](file:///Users/sethurama/DEV/LM/learning-mate/backend/app/config.py)

### Problem Statement
When starting Luminary using `make dev` or `make start`, the FastAPI backend initializes silently even if Ollama is not running or the model `llama3.2` hasn't been pulled. The user only discovers this when they send their first chat message, which hangs or fails with an obscure error.

### Proposed Solution
Add a lightweight configuration check and network ping to Ollama during FastAPI startup:
1. In `app/main.py`'s lifespan/startup event, send an async HTTP request to the Ollama endpoint `http://127.0.0.1:11434/api/version`.
2. Also check if the default chat model `LITELLM_DEFAULT_MODEL` is pulled in Ollama.
3. If the connection fails or the model is missing, log a highly visible warning banner in the terminal stdout (using color formatting if possible) detailing how to start Ollama or pull the model.
4. **Note**: Do not block the server startup or crash the app. Offline features (like PDF viewing or notes) must still work.

---

## 4. 🔴 [Challenging][Backend]: Dynamic Context Budget Scaling for Chat History
* **Difficulty**: `difficulty/challenging`
* **Area**: `area/backend`
* **Target Files**:
  * [qa.py](file:///Users/sethurama/DEV/LM/learning-mate/backend/app/services/qa.py)
  * [chat_graph.py](file:///Users/sethurama/DEV/LM/learning-mate/backend/app/runtime/chat_graph.py)

### Problem Statement
Luminary feeds retrieved text chunks up to `QA_CONTEXT_TOKEN_BUDGET` (default 1500 tokens) into the local LLM. However, local models like Llama 3.2 3B have a default context window of `2048` tokens (`OLLAMA_NUM_CTX`). When a user engages in a long conversation, the chat history size grows and eventually exceeds the remaining token budget, causing Ollama to silently truncate older history or the retrieval context itself.

### Proposed Solution
Implement a dynamic context allocator in the synthesis stage:
1. Count the exact number of tokens in the prompt template, system prompt, and active conversation history.
2. Dynamically adjust `QA_CONTEXT_TOKEN_BUDGET` for that request:
   `available_retrieval_budget = QA_NUM_CTX - (history_tokens + system_prompt_tokens + safety_buffer)`
3. If `available_retrieval_budget` is too low (e.g. less than 500 tokens), compress/summarize the oldest chat history turns using a sliding window to free up space, ensuring grounding context is never completely starved.

---

## 5. 🔴 [Challenging][Deployment]: GPU Detection and Auto-tuning in Installer Scripts
* **Difficulty**: `difficulty/challenging`
* **Area**: `area/deployment`
* **Target Files**:
  * [install.sh](file:///Users/sethurama/DEV/LM/learning-mate/scripts/install.sh)
  * [install.ps1](file:///Users/sethurama/DEV/LM/learning-mate/scripts/install.ps1)

### Problem Statement
Ollama runs significantly faster with GPU acceleration. However, many users have misconfigured graphics drivers or compile issues. The installer scripts run a single configuration without verifying whether the host's GPU is successfully utilized by Ollama.

### Proposed Solution
1. Add diagnostics in `install.sh` and `install.ps1` to detect the hardware profile:
   * **macOS**: Check if running on Apple Silicon (M1/M2/M3) vs. Intel.
   * **Windows/Linux**: Query `nvidia-smi` or check for AMD ROCm support.
2. Call the Ollama API `/api/show` or run a dummy inference to detect if it uses the GPU.
3. Automatically adjust backend `.env` values such as `ENRICHMENT_VISION_CONCURRENCY` and print warnings if Ollama fell back to CPU execution.
