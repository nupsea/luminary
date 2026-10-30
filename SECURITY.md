# Security policy

Report a vulnerability privately: on GitHub, **Security → Report a vulnerability**
([direct link](https://github.com/nupsea/luminary/security/advisories/new)). Never in a public
issue or PR. The report and the fix are discussed on that private advisory.

Only the latest release is supported; a fix ships as a new release.

These matter most, because Luminary's claim is that a library stays on its owner's machine:

- Anything that sends library content off the machine in Private mode, or more than the question
  and its retrieved passages with an API key (README, "Faster answers").
- The backend API (port 7820) and device pairing: a request served without the access it should
  need.
- The one-command installers (`scripts/get-luminary.sh`, `scripts/get-luminary.ps1`), which are
  run piped into a shell.
- How API keys are stored. Docker and headless Linux keep a saved key in the library database in
  plain text by design (README); that alone is not a vulnerability.
