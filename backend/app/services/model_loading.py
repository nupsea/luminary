"""Process-wide lock serializing HuggingFace/torch model construction.

`transformers.from_pretrained` mutates process-global state while it builds a
model (`no_init_weights` swaps out `torch.nn.init.*`, weights are materialized
from a meta-device init). Two concurrent loads in different threads therefore
corrupt each other: one model keeps meta parameters that are never filled, and
its final `.to(device)` raises "Cannot copy out of meta tensor". Every torch
model load in this process -- embedder, GLiNER, cross-encoder -- must be built
while holding this lock.
"""

import threading

MODEL_LOAD_LOCK = threading.RLock()
