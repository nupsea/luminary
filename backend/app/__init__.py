"""Luminary backend.

Switches off third-party network defaults before any library reads them at import:
litellm's remote price list and huggingface_hub telemetry (I-57). `setdefault`, so an
operator can opt back in.

Verifies TLS against the operating system's trust store (I-59), before any client
builds a context, and uses the system proxy with loopback exempt (`proxy_env`).
"""

import os

import truststore

from app.proxy_env import pin_system_proxy

for _key, _value in (
    ("LITELLM_LOCAL_MODEL_COST_MAP", "True"),
    ("HF_HUB_DISABLE_TELEMETRY", "1"),
):
    os.environ.setdefault(_key, _value)

truststore.inject_into_ssl()
pin_system_proxy()
