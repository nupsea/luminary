"""Luminary backend.

Switches off third-party network defaults before any library reads them at import:
litellm's remote price list and huggingface_hub telemetry (I-57). `setdefault`, so an
operator can opt back in.
"""

import os

for _key, _value in (
    ("LITELLM_LOCAL_MODEL_COST_MAP", "True"),
    ("HF_HUB_DISABLE_TELEMETRY", "1"),
):
    os.environ.setdefault(_key, _value)
