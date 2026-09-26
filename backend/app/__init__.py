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
    # A scanning proxy sends nothing until it holds the whole file: the 1.1GB
    # entity model failed at the hub's 10s read timeout behind one, while the
    # 128MB reranker arrived in 9s. Downloads are user-started and show progress.
    ("HF_HUB_DOWNLOAD_TIMEOUT", "300"),
):
    os.environ.setdefault(_key, _value)

truststore.inject_into_ssl()
pin_system_proxy()
