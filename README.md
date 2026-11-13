<div align="center">

# HoundBrowser

### A real browser. A deliberate API.

Scoped browser automation for AI agents, with live observation and inspectable evidence.

[Documentation](https://ops.warhoundai.com/docs/houndbrowser) · [Quickstart](#quickstart) · [API](docs/api.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-b51235)](LICENSE)

</div>

HoundBrowser is a self-hosted browser runtime built on Playwright and Chromium. Your application supplies the model, orchestration, authorization, and budgets. HoundBrowser executes explicit browser commands through a versioned API and returns what it observed.

```text
Your agent → authenticated, scoped API → Chromium
                                         ↓
              observations · live frames · evidence
```

No WarHound account or model-provider key is required. No shell, host-filesystem, or CDP endpoint is exposed to agents.

## Why HoundBrowser?

- **One protocol for every model.** Python, JavaScript, and HTTP clients; no inference dependency.
- **Scope enforced in code.** Approved HTTPS origins, explicit write paths, and a public-only pinned-DNS proxy.
- **State you can reason about.** Revision-scoped element handles, serialized commands, idempotent command IDs, and explicit uncertain outcomes.
- **A view without a control channel.** One-use, short-lived WebSocket tickets for read-only events and masked frames.
- **Evidence you can inspect.** Screenshot artifacts with SHA-256 digests and authenticated downloads.
- **Bounded synthetic experiments.** Rate-limit and alias fixtures stop on throttling, failures, or excessive latency; no mail is sent.

## Quickstart

Python 3.11+ and Chromium are required. This initial release installs from source; a PyPI or npm publication is not implied.

```bash
git clone https://github.com/warhoundai/HoundBrowser.git
cd HoundBrowser
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install --with-deps chromium

export HOUNDBROWSER_API_KEYS="$(python -c 'import json,secrets; print(json.dumps({"local":secrets.token_urlsafe(32)}))')"
export HOUNDBROWSER_ALLOWED_ORIGINS='["https://example.com"]'
houndbrowser serve --host 127.0.0.1 --port 8080
```

Keep the generated service key in your backend. Never put it into a model prompt or client-side application. The service binds to loopback by default. Use TLS and a dedicated trust domain for remote deployments.

In a second process using the same environment:

```python
import json
import os
from houndbrowser.client import Client

key = json.loads(os.environ["HOUNDBROWSER_API_KEYS"])["local"]
with Client("http://127.0.0.1:8080", api_key=key) as browser:
    session = browser.create("https://example.com")
    try:
        result = browser.run(session["id"], "navigate", {"url": "https://example.com"})
        print(result["result"]["title"])
    finally:
        browser.close(session["id"])
```

See [examples/](examples/) for JavaScript, HTTP, and live observation.

## Capability map

| Area | Available capabilities |
| --- | --- |
| Navigation | Navigate, back, forward, tabs, switch and close tabs |
| Interaction | Click, type, select, keyboard, scroll |
| Observation | Structured page text, element handles, screenshots, diagnostics |
| HTTP | Scoped requests, bounded responses, browser-owned cookies |
| Assertions | Text presence, element count, URL path, response statuses |
| Page JavaScript | Unauthenticated sessions only; network scope still applies |
| Lifecycle | Command IDs, cancellation, close, replayable events, idle cleanup |

The service does not discover targets, authorize testing, choose security payloads, or claim that a successful response is a vulnerability. Synthetic rate and alias experiments require explicitly approved `/__houndbrowser_test__/` endpoints.

## Security and deployment

Read the [security model](docs/security.md) before exposing the service. The standalone server is a **single-node reference runtime**, not an adversarial multi-tenant sandbox. Each session starts a Chromium process, but sessions share the API process and host. Deploy a separate container, VM, or isolated task per trust domain. Authenticated profiles come only from operator configuration; arbitrary page JavaScript is blocked in those sessions.

SQLite persists status, events, and artifacts. On restart, unfinished commands become `outcome_unknown` and sessions close. No mutation is automatically replayed. Run one ASGI worker per database. Apply your own encrypted storage, backups, retention policy, and inference/tool budgets.

## Development

```bash
pip install -e '.[dev]'
python -m playwright install --with-deps chromium
pytest
node --test sdk/js/*.test.mjs
python -m build
```

Tests use controlled fixtures. They do not run against customer websites. See [CONTRIBUTING.md](CONTRIBUTING.md) and [the release process](docs/releases.md).

## License

Copyright 2026 WarHound AI. Licensed under [Apache 2.0](LICENSE). See [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency and distribution notes.
