"""Where an API key ends up must match what the README promises.

The README said Settings "stores it in your OS keychain rather than a file".
That is true natively and false in Docker -- the install path recommended for
Intel Mac, Windows and Linux. A container has no OS keyring, `_keyring_set`
returns False, and the key is written to SQLite behind a `__plain__:` prefix.

The fallback itself is reasonable; a key has to live somewhere. The defect was
making an unqualified claim about credential handling that does not hold on the
most-recommended install.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = (REPO / "README.md").read_text()


def test_the_readme_does_not_claim_the_keychain_unconditionally():
    from app.services.settings_service import _PLAINTEXT_PREFIX

    assert _PLAINTEXT_PREFIX, "the plaintext fallback still exists"
    assert "plain text" in README, "the fallback has to be disclosed where the claim is made"


def test_the_disclosure_names_the_install_it_applies_to():
    """"Sometimes plaintext" is not actionable; a user needs to know if it is
    them."""
    idx = README.find("plain text")
    nearby = README[max(0, idx - 400) : idx + 200]
    assert "Docker" in nearby
