# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup (always use venv)
```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-test.txt
```

Never install packages directly on the machine — always activate the venv first.

### Run tests
```sh
# Run all tests
pytest tests/test_redalert.py -v

# Run a single test
pytest tests/test_redalert.py::test_fetch_alert_success -v

# Run with coverage
coverage run -m pytest tests/test_redalert.py -v
coverage report -m --include="redalert.py"
```

### Run the service locally
```sh
export MQTT_HOST=mqtt.example.com
export MQTT_USER=myuser
export MQTT_PASS=mypassword
export HEALTH_PORT=8080   # optional, default 8080
python redalert.py
```

### Docker
```sh
docker build -t techblog/redalert .
```

## Architecture

The entire service is a single file: `redalert.py`. There are no packages or modules.

**Data flow:**
1. `monitor()` — the main async loop — opens an `aiohttp.ClientSession` and an `aiomqtt.Client` connection
2. Every second, `fetch_alert(session)` polls `https://www.oref.org.il/WarningMessages/alert/alerts.json` with browser-like headers (required by Oref API)
3. Responses are parsed into an `AlertObject` dataclass
4. New alerts (not seen in the in-memory `alerts` dict) that pass the test-alert filter are published via `publish_alert(mqtt_client, alert)` to two MQTT topics:
   - `${MQTT_TOPIC}/cat/{alert.cat}` — structured JSON with title, data, desc
   - `${MQTT_TOPIC}/raw_data` — raw JSON string from the API
5. `alerts` dict tracks published alert IDs with timestamps; `cleanup_alerts()` removes entries older than `ALERT_TTL` (1 hour), called every 60 seconds

**MQTT reconnection:** On `aiomqtt.MqttError` or any other exception, the outer loop in `monitor()` retries after 5 seconds.

**Timeouts:** `aiohttp.ClientSession` is created with `sock_connect=5s, sock_read=10s`. `aiomqtt.Client` is created with `timeout=10s`. Both prevent indefinite hangs on network stalls.

**Health endpoint:** `run_health_server()` runs alongside `monitor()` via `asyncio.gather`. It serves `GET /health` on `HEALTH_PORT` (default `8080`):
- `200 {"status": "ok", "last_heartbeat_ago": N}` — loop is running normally
- `503 {"status": "frozen", "last_heartbeat_ago": N}` — no heartbeat for > `HEALTH_THRESHOLD` (30 s) or loop never started

The heartbeat (`last_heartbeat`) is updated each iteration after `asyncio.sleep(1)`. With `sock_read=10` and MQTT `timeout=10`, worst-case gap is ~22 s, so `HEALTH_THRESHOLD=30` gives a safe margin.

**Debug mode:** When `DEBUG=True`, the service substitutes a hardcoded Hebrew alert payload with an incrementing `id` instead of fetching from the API.

## Versioning and CI

Version is stored in the `VERSION` file (plain text semver). **Do not edit `VERSION` manually** — it is managed by CI.

### Creating a new release

Releases are fully automated on push to `main`. To trigger one:

1. Commit your changes using the correct prefix to control the version bump:
   - `feat:` or `feature:` → **minor** bump (e.g. 4.3.21 → 4.4.0)
   - `break:` or `breaking:` → **major** bump (e.g. 4.3.21 → 5.0.0)
   - anything else (e.g. `fix:`, `chore:`) → **patch** bump (e.g. 4.3.21 → 4.3.22)
2. Push to `main`.

The `Create Release` workflow then:
- Reads the current version from `VERSION`
- Scans all commits since the last git tag to determine the bump type
- Calculates the new version, creates a GitHub release and tag, then commits the updated `VERSION` file back to `main`

After `Create Release` succeeds, the `Docker Build` workflow automatically:
- Runs `pytest` with coverage (build fails if coverage < 70%)
- Builds and pushes the Docker image to GHCR tagged as both `latest` and the new semver
