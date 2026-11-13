# Deploying HoundBrowser

Use the supplied Dockerfile or run the CLI on a dedicated host. Configure `HOUNDBROWSER_API_KEYS` as a JSON map of tenant IDs to independent random keys, each at least 32 characters, and `HOUNDBROWSER_ALLOWED_ORIGINS` as a JSON array of approved HTTPS origins. Never expose either through client-side code. Set `HOUNDBROWSER_DATABASE` to a file on encrypted persistent storage; the container uses `/data/houndbrowser.sqlite3`.

```sh
docker build -t houndbrowser:0.1.0 .
docker run --rm --init --shm-size=1g \
  -p 127.0.0.1:8080:8080 --env-file .env \
  -v houndbrowser-data:/data houndbrowser:0.1.0
```

Run one ASGI process per database. Sessions live in that process; SQLite persists command status, events, and artifacts. On restart, active sessions close and incomplete commands become uncertain. Do not run multiple Uvicorn workers or blindly route a session between replicas.

The default maximum is eight sessions, with eight tabs each, a 300-second productive-idle timeout, 20 KB command envelopes, and bounded response/evidence sizes. The reference service is for one operator trust domain. Use a separate container, VM, or managed task for untrusted tenants. Never mount host sockets, production credentials, or a user's normal browser profile.

Put a TLS reverse proxy and service authentication at the edge. Restrict inbound traffic, use encrypted storage, rotate service keys, monitor resource use, back up SQLite, and define your evidence-retention policy. These are operator responsibilities; the runtime does not configure a cloud account or retain evidence indefinitely by contractual promise.

For custom credential profiles, construct `Settings(profiles={...})` in an operator-owned Python entrypoint and pass it to `create_app`. A profile has `origin` and `credentials` with `url`, `username`, `password`, `usernameSelector`, `passwordSelector`, `submitSelector`, and `successSelector`. Read secrets from your secret manager inside that entrypoint, never from model arguments. Authenticated sessions reject `evaluate` and use constrained assertions.
