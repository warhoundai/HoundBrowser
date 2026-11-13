# HTTP and event API

All routes except `/health` require `Authorization: Bearer <service-key>`. The key selects a tenant; tenant names cannot be supplied by callers. JSON bodies are capped at 20 KB. The versioned prefix is `/v1/browser`.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/sessions` | Start an approved-origin browser; return 201 when ready |
| GET | `/sessions/{id}` | State, scope and current revision |
| DELETE | `/sessions/{id}` | Close the session; repeated close is safe |
| POST | `/sessions/{id}/commands` | Accept a serialized command; return 202 |
| GET | `/sessions/{id}/commands/{command}` | Retrieve the original command outcome |
| POST | `/sessions/{id}/cancel` | Revoke the current epoch and cancel work |
| GET | `/sessions/{id}/events?after=123` | Up to 200 stored events after the cursor |
| GET | `/sessions/{id}/artifacts/{sha256}` | Authenticated JPEG with digest header |
| POST | `/sessions/{id}/viewer` | One-use, 60-second read-only WebSocket grant |

The service serves its OpenAPI schema at `/openapi.json` behind service authentication.

## Create a session

```json
{"scope":{"origin":"https://example.com","methods":["GET","HEAD"],"writePaths":[],"websockets":false}}
```

The origin must be in `HOUNDBROWSER_ALLOWED_ORIGINS`. Write methods require explicit paths. Optional credential profile IDs must be configured by the operator for that exact origin.

## Submit a command

```json
{"id":"observe-1","idempotencyKey":"observe-1","action":"observe","args":{},"revision":0}
```

Use the command ID as its idempotency key. Reusing it with different content returns 409. Only one command may hold the session lease. A stale revision returns `STALE_PAGE`; obtain a fresh observation before choosing the next action. Never silently replay a state-changing command after a timeout or `outcome_unknown`.

Actions: `navigate`, `observe`, `click`, `type`, `select`, `scroll`, `key`, `back`, `forward`, `tabs`, `new_tab`, `switch_tab`, `close_tab`, `screenshot`, `diagnostics`, `http`, `evaluate`, `assert`, `rate_test`, `alias_test`.

See `browser.py` and generated OpenAPI for exact command arguments. The initial action envelope intentionally uses an argument object; action-specific JSON schemas are not yet advertised as generated provider function declarations.

## Live observation

Request `{"frames":true}` from the viewer route. Connect to the returned path using WebSocket subprotocols `houndbrowser` and `ticket.<grant>`. Tickets are single-use and valid for connection establishment for 60 seconds. Keep tickets out of URL query strings and access logs. Viewers can send only the literal text `ping`; other messages close the connection. Frames contain JPEG data in Base64 and a monotonic sequence. Event queues are bounded and may drop superseded events; recover durable events by cursor.

The reference service sends at most two frames per second per viewer. Frames consume browser CPU, not model tokens. Frame delivery is not an inference loop. A slow viewer never authorizes extra commands.

## Action arguments

| Action | Arguments |
| --- | --- |
| `navigate` | `url`: approved HTTPS URL |
| `observe`, `tabs`, `new_tab`, `back`, `forward`, `screenshot`, `diagnostics` | Empty object |
| `click` | `elementId`: handle from the current observation |
| `type` | `elementId`, `text` (at most 2,000 characters) |
| `select` | `elementId`, `value` |
| `scroll` | `pixels` (clamped to −2,000…2,000) |
| `key` | `key`: Enter, Tab, Escape, arrow keys, Space, or Backspace |
| `switch_tab`, `close_tab` | `tabId`: ID returned by `tabs` |
| `http` | `url`, optional `method`, optional JSON-string `body`; write scope is enforced |
| `evaluate` | `script` (at most 10,000 characters), unauthenticated sessions only |
| `assert` | `check`: text_present, element_count, url_path, or response_status; text_present also takes `text` |
| `rate_test` | `url`, `experimentId`, `requests` (1…60); synthetic endpoint only |
| `alias_test` | `url`, `experimentId`, `method: POST`, `mailSink: fixture`, `requests` (at most 3); synthetic endpoint only |

DOM changes emit structured `observation` events independently of model inference. Monitoring does not extend the productive-idle lease. Frame capture and observation share the browser mutation lock so an observation never reads temporary screenshot masking markup.
