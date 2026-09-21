---
description: Which engine answers, what leaves the machine, and which hosts may run a local model. Read before touching routing, the engine offer, API keys or host_support.
---

# Engine modes and supported hosts

## Modes

One stored setting, `llm_mode`, decides which engine runs synthesis. The default is `private`.

| Mode | Interactive work (ask, explain, practice) | Background work (summaries, tags, titles) |
|---|---|---|
| `private` | local (Ollama) | local |
| `hybrid` | the user's cloud key | local |
| `cloud` | the user's cloud key | the user's cloud key |

`settings_service.get_effective_routing` resolves the route. **No key still means a fully working
local app** (I-16), which is why hybrid is offered and never defaulted.

**Only synthesis is routable.** Embedding, retrieval, reranking, transcription, entity extraction and
the learner record stay local in every mode, and `llm_routing.routing_report` reports them as fixed.
A hosted embedder is a different vector space, so it is a full re-embed and never a setting (I-9).
Routing extraction or reranking out would put document text on the wire instead of one question and
its passages; that was proposed and rejected (roadmap, "Abandoned").

Every answer carries a receipt: engine, latency, cost, and what left the machine (N passages, M
tokens, which provider). Retrieval renders before generation, so source chips paint while the answer
streams.

## The engine offer

`EngineChoice` asks the question. It is mounted by `FirstRunGuide` on an empty Hub and by
`EngineOffer` on a non-empty one, so an upgraded library is asked too. Both render `EngineChoice`
rather than restating it: two wordings about what leaves the machine are two things to keep true.

- **Whether the user chose is the row, not the value.** `private` reads the same chosen or defaulted,
  so `get_llm_settings` reports `mode_chosen` from whether an `llm_mode` row exists
  (`test_a_library_that_was_never_asked_reports_no_choice`).
- Dismissing the offer is stored separately as `llm_offer_dismissed`. Declining to decide is not a
  decision.
- A provider change carries that provider's default model; a model picked for the provider being
  kept survives (I-53). Otherwise picking Anthropic routed `anthropic/gpt-4o-mini`.
- Where a key lands is read from the machine: `keyring_available` says whether it goes to the OS
  keychain or falls back to a plaintext row in the library database (Docker, headless Linux). The
  key panel's sentence follows it, and README states the split per install path.

## Latency: what the cloud buys

`make measure-ttft` reads the figure each answer's receipt reports, so a quoted number is the one a
user sees, and `scripts/measure_ttft.py` refuses to average across arms. Measured 2026-09-10, one
machine, same document and question, 20 passages, 1500-token budget, five runs per arm:

| | local (`ollama/qwen3.5:4b`) | cloud (`openai/gpt-5.6-sol`) |
|---|---|---|
| first token, median | 3.14s | 2.30s |
| first token, range | 2.21-3.54s | 1.62-2.90s |
| complete answer | 13.8-36.6s | 5.7-10.8s |

Both arms retrieve locally and retrieval is most of the wait before the first token, so **the cloud
buys the finish, not the start.** Quoting it as "faster to first token" quotes noise. A genuinely slow
host is unmeasured here. The slow-host context budget that halves passages has no quality number
behind it (#100); do not take a second latency win out of content.

## Supported hosts

`app/host_support.py` decides whether local inference is worth offering, and `HostSupportBanner`
states the verdict wherever the user is. It refuses on three grounds:

| Reason | Case that decided it |
|---|---|
| `intel_mac` | no lancedb wheel for a native install; Docker on macOS never reaches Metal. ~6 tok/s, ~121s per question |
| `no_accelerator` / `container_without_accelerator` | a CPU-only host or container |
| `under_memory_floor` | under `memory_profile._STANDARD_MIN_RAM_GB` (16). Docker Desktop presents a 16 GB Mac as ~7 GB. Currently also refuses a 16 GiB Linux box (#139) |

- **The check is the accelerator, never the install method.** Refusing containers would refuse Linux
  with the NVIDIA container toolkit, the fastest way to run this app. `test_host_support.py` fails CI
  if a container with a GPU is refused; S251 guards the wire contract.
- One probe with a branch per vendor and platform (`has_nvidia_accelerator`, `_has_amd_accelerator`).
  Windows reads the driver DLLs Ollama loads, since it has no `/dev`. A second copy of the policy
  would eventually disagree with this one.
- **The refusal sits in `LLMService._resolve_model`**, keyed on the model that will actually run, so
  a pinned local model is refused on the same terms. Not in `get_effective_routing`: that function
  describes routes as often as it picks one, and raising there broke
  `test_a_fresh_install_on_8gb_resolves_every_role_to_one_model`. A cloud model is never refused.
- Background work is refused too, so enrichment does not run on an unsupported host unless the user
  picks Cloud mode (roadmap, the 0.13.0 section; `tests/test_engine_mode_on_unsupported_host.py`).
- `LUMINARY_HOST_SUPPORTED=1` declares the host supported. It is needed under compose, where the
  model runs in a sibling container and the app has no device to find
  (`docker-compose.gpu.yml`, `make docker-run-gpu`), and it is the documented escape hatch. No
  AMD/ROCm overlay ships: an untested device block that fails at `up` is worse than none.
