"""Luminary backend.

Runs before anything under `app` is imported, which is the only point early
enough to switch off what third-party libraries do on the network by default:
both read these variables once, at their own import.

  LITELLM_LOCAL_MODEL_COST_MAP  `import litellm` otherwise fetches a price list
                                from raw.githubusercontent.com on every start.
  HF_HUB_DISABLE_TELEMETRY      huggingface_hub otherwise reports usage on the
                                downloads setup makes.

A running app contacts a third party only for something the user asked for:
ingesting a URL, a cloud model they configured, a component they installed.
`setdefault`, so an operator can still opt back in.
"""

import os

for _key, _value in (
    ("LITELLM_LOCAL_MODEL_COST_MAP", "True"),
    ("HF_HUB_DISABLE_TELEMETRY", "1"),
):
    os.environ.setdefault(_key, _value)
