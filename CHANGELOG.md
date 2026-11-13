# Changelog

## 0.1.0

Initial standalone release of HoundBrowser.

- API-first Chromium runtime with approved-origin enforcement and public-only pinned-DNS egress.
- Authenticated sessions, serialized commands, revision checks, command ID idempotency, cancellation, and explicit uncertain outcomes.
- SQLite status/event/evidence persistence and safe restart behavior.
- Read-only WebSocket observation, masked frames, and authenticated SHA-256 screenshot artifacts.
- Python and JavaScript clients, controlled fixture tests, container packaging, and operational documentation.

This is an initial 0.x release. The standalone server is single-node and must be deployed separately per trust domain. It does not include WarHound's proprietary model orchestration, billing, account system, production deployment credentials, or cloud control plane.
