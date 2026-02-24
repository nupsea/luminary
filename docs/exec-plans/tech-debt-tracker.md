# Technical Debt Tracker

| ID | Description | Priority | Owner | Created |
|----|-------------|----------|-------|---------|
| TD-001 | Notes data model lacks section_id — note indicators in DocumentReader cannot persist across page reloads | med | ralph | 2026-02-25 |
| TD-002 | datetime.utcnow() deprecated in Python 3.12+ — notes router uses it; replace with datetime.now(UTC) | low | ralph | 2026-02-25 |
| TD-003 | Bundle size 673KB gzipped (warning threshold 500KB) — consider dynamic import() for Sigma.js/Graphology | low | ralph | 2026-02-25 |
