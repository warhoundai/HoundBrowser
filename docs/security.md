# Security policy

## Supported versions

The current 0.1.x release line receives security fixes. Older prereleases are unsupported. Initial 0.x APIs may change; pin an exact version and read release notes before updating.

## Reporting privately

Use the repository's **Security → Report a vulnerability** feature if available. Otherwise contact the WarHound account owner through the contact channel listed at https://warhoundai.com before sharing exploit details. Do not open a public issue containing credentials, customer data, or an active exploitation recipe. No response-time SLA or bounty is promised.

Include the affected version, configuration and deployment boundary, a minimal reproduction against your own fixture, expected versus observed behavior, and impact. Redact secrets and unrelated data.

## Trust model

HoundBrowser's standalone server runs one API process with separate Chromium processes on the same host. It is **not an adversarial multi-tenant sandbox**. Isolate deployments by trust domain using containers, VMs, or separate managed tasks. Bind the service privately, require TLS remotely, rotate service keys, and use encrypted storage with a retention policy.

Only operator-approved public HTTPS origins are accepted. DNS answers are checked and connections are pinned to validated public IPs. Every resource request remains in scope; private network and cloud metadata addresses are unavailable. No shell, host filesystem, or CDP interface is exposed.

Authenticated sessions use operator-managed credential profiles and reject arbitrary page JavaScript. Input fields are masked in screenshots, and known secret values are redacted from structured output. Redaction is best effort: hostile pages can re-encode or visually transform sensitive information. Do not use production credentials for untrusted pages.

Page content, console output, and tool results are untrusted observations. They cannot authorize new origins or override your agent's instructions. Configure model-side prompt injection resistance and application-side authorization independently.

Cancellation cannot undo a request already delivered to the target. On uncertain outcomes, inspect state instead of replaying a mutation. An allowlist is not proof of target ownership or permission; operators must obtain authorization for their testing.
