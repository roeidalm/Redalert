# RedAlert Relay System

The **RedAlert Relay System** is a Python-based service that fetches real-time alerts from the Israeli Oref API and relays them to MQTT topics. It is designed for reliability, supports asynchronous operation, and is easily deployable via Docker.

---

## Features

- **Fetches alerts** from the official Oref API using `aiohttp`.
- **Relays alerts** to MQTT topics using `aiomqtt`.
- **Filters out test alerts** (configurable via `INCLUDE_TEST_ALERTS`).
- **Prevents duplicate publishing** and cleans up old alerts (1 hour retention).
- **MQTT keep-alive** publishes a status message every configurable interval (default 5 min) for Home Assistant monitoring.
- **MQTT-aware health check** — returns HTTP 503 if MQTT publishing is stale, enabling Kubernetes to auto-restart the pod.
- **Area lookup endpoint** — `/area?lat=...&lon=...` returns the alert area and shelter time for a given coordinate.
- **Configurable** via environment variables.
- **Ready for Docker, Docker Compose, and Kubernetes deployment**.

---

## Requirements

- Python 3.12+ (if running locally)
- Docker (recommended for deployment)
- MQTT broker (e.g., Mosquitto)

---

## Environment Variables

| Variable              | Description                                   | Default         | Example                |
|-----------------------|-----------------------------------------------|-----------------|------------------------|
| `MQTT_HOST`           | MQTT broker address                           | `127.0.0.1`     | `mqtt.example.com`     |
| `MQTT_PORT`           | MQTT broker port                              | `1883`          | `1883`                 |
| `MQTT_USER`           | MQTT username                                 | `user`          | `myuser`               |
| `MQTT_PASS`           | MQTT password                                 | `password`      | `mypassword`           |
| `MQTT_TOPIC`          | Base MQTT topic for alerts                    | `/redalert`     | `/alerts`              |
| `INCLUDE_TEST_ALERTS` | Include test alerts (True/False)              | `False`         | `True`                 |
| `DEBUG`               | Enable debug mode with test data (True/False) | `False`         | `True`                 |
| `HEALTH_PORT`         | Port for the health/area HTTP endpoint        | `8080`          | `9090`                 |
| `KEEPALIVE_INTERVAL`  | Seconds between MQTT keep-alive messages      | `300`           | `120`                  |

---

## MQTT Topics

The service publishes to the following MQTT topics:

### Alert Topics

Published when a new alert is received from the Oref API:

- **`{MQTT_TOPIC}/cat/{category}`** — Structured alert data (JSON).

  ```json
  {
    "title": "ירי רקטות וטילים",
    "data": ["ירושלים - מערב", "ירושלים - צפון"],
    "desc": "היכנסו למרחב המוגן ושהו בו 10 דקות"
  }
  ```

- **`{MQTT_TOPIC}/raw_data`** — Full raw alert payload from the API (JSON string).

  ```json
  {
    "id": "133908130700000000",
    "cat": "10",
    "title": "ירי רקטות וטילים",
    "data": ["ירושלים - מערב", "ירושלים - צפון"],
    "desc": "היכנסו למרחב המוגן ושהו בו 10 דקות"
  }
  ```

### Keep-Alive Topic

Published every `KEEPALIVE_INTERVAL` seconds (default: 300s / 5 min):

- **`{MQTT_TOPIC}/keepalive`** — Service status for monitoring.

  ```json
  {
    "status": "online",
    "mqtt": "connected",
    "oref": "ok",
    "uptime": 3600,
    "timestamp": 1712345678
  }
  ```

  | Field       | Description                                                            |
  |-------------|------------------------------------------------------------------------|
  | `status`    | Always `"online"` when published                                      |
  | `mqtt`      | Always `"connected"` (published from within the MQTT client context)   |
  | `oref`      | `"ok"` if last successful Oref fetch was within 30s, `"failing"` otherwise |
  | `uptime`    | Seconds since the MQTT connection was established                      |
  | `timestamp` | Unix timestamp of the message                                          |

---

## Health Endpoint

The service exposes an HTTP health endpoint at `GET /health` on `HEALTH_PORT` (default `8080`).

| Status Code | Response                              | Meaning                                                     |
|-------------|---------------------------------------|-------------------------------------------------------------|
| `200`       | `{"status": "ok", ...}`               | Service is running and MQTT is healthy                      |
| `503`       | `{"status": "frozen", ...}`           | Monitor loop has stopped (no heartbeat for >30s)            |
| `503`       | `{"status": "mqtt_stale", ...}`       | MQTT has not published successfully within the grace period |

The MQTT staleness grace period is `KEEPALIVE_INTERVAL + 60` seconds, allowing time for the first keep-alive after startup.

---

## Home Assistant Integration

### MQTT Sensor for Keep-Alive Monitoring

Add to your `configuration.yaml`:

```yaml
mqtt:
  sensor:
    - name: "RedAlert Status"
      state_topic: "/redalert/keepalive"
      value_template: "{{ value_json.status }}"
      json_attributes_topic: "/redalert/keepalive"
      json_attributes_template: >
        {{ value_json | tojson }}
      expire_after: 300

    - name: "RedAlert Oref Status"
      state_topic: "/redalert/keepalive"
      value_template: "{{ value_json.oref }}"

    - name: "RedAlert Uptime"
      state_topic: "/redalert/keepalive"
      value_template: "{{ value_json.uptime }}"
      unit_of_measurement: "s"
      device_class: duration
```

### Alert Notification Automation

Trigger a notification when a new alert is received:

```yaml
automation:
  - alias: "RedAlert - Rocket Alert Notification"
    trigger:
      - platform: mqtt
        topic: "/redalert/cat/+"
    action:
      - service: notify.mobile_app_my_phone
        data:
          title: "{{ trigger.payload_json.title }}"
          message: "{{ trigger.payload_json.data | join(', ') }}"
          data:
            priority: high
            channel: alert
            ttl: 0
```

### Service Offline Alert

Get notified when the RedAlert service goes offline (no keep-alive for 10 minutes):

```yaml
automation:
  - alias: "RedAlert - Service Offline Alert"
    trigger:
      - platform: state
        entity_id: sensor.redalert_status
        to: "unavailable"
        for:
          minutes: 10
    action:
      - service: notify.mobile_app_my_phone
        data:
          title: "RedAlert Service Offline"
          message: "The RedAlert relay service has not sent a keep-alive in over 10 minutes."
```

### Oref API Failure Alert

Get notified when the Oref API polling is failing:

```yaml
automation:
  - alias: "RedAlert - Oref API Failing"
    trigger:
      - platform: state
        entity_id: sensor.redalert_oref_status
        to: "failing"
        for:
          minutes: 5
    action:
      - service: notify.mobile_app_my_phone
        data:
          title: "RedAlert Oref API Issue"
          message: "The Oref API polling has been failing for 5 minutes. Alerts may not be received."
```

### Raw Alert Data Sensor

Capture the full raw alert payload for advanced automations:

```yaml
mqtt:
  sensor:
    - name: "RedAlert Raw Data"
      state_topic: "/redalert/raw_data"
      value_template: "{{ value_json.id }}"
      json_attributes_topic: "/redalert/raw_data"
      json_attributes_template: >
        {{ value_json | tojson }}
```

---

## Running with Docker

### 1. Build the Docker Image

```sh
docker build -t techblog/redalert .
```

### 2. Run with Docker Compose

Edit `docker-compose.yaml` to set your MQTT broker credentials and preferences:

```yaml
version: "3.6"
services:
  redalert:
    image: techblog/redalert
    container_name: redalert
    restart: always
    environment:
      - MQTT_HOST=[Broker Address]
      - MQTT_USER=[Broker Username]
      - MQTT_PASS=[Broker Password]
      - INCLUDE_TEST_ALERTS=False
      - MQTT_PORT=1883
      - MQTT_TOPIC=/redalert
      - KEEPALIVE_INTERVAL=120
      - DEBUG=False
```

Then start the service:

```sh
docker-compose up -d
```

### 3. Run Directly with Docker

```sh
docker run -d \
  --name redalert \
  -e MQTT_HOST=mqtt.example.com \
  -e MQTT_USER=myuser \
  -e MQTT_PASS=mypassword \
  -e INCLUDE_TEST_ALERTS=False \
  -e MQTT_PORT=1883 \
  -e MQTT_TOPIC=/redalert \
  -e KEEPALIVE_INTERVAL=120 \
  -e DEBUG=False \
  techblog/redalert
```

---

## Running Locally (for Development)

1. **Install dependencies:**

   ```sh
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Set environment variables** (or use a `.env` file):

   ```sh
   export MQTT_HOST=mqtt.example.com
   export MQTT_USER=myuser
   export MQTT_PASS=mypassword
   export INCLUDE_TEST_ALERTS=False
   export MQTT_PORT=1883
   export MQTT_TOPIC=/redalert
   export DEBUG=False
   ```

3. **Run the script:**

   ```sh
   python redalert.py
   ```

---

## How It Works

- The service continuously polls the Oref API for new alerts (every second).
- Each new alert (not previously seen and not a test alert, unless allowed) is published to the configured MQTT topics.
- Alerts are tracked for 1 hour to prevent duplicate publishing.
- Old alerts are cleaned up every 60 seconds.
- A keep-alive message is published to MQTT every `KEEPALIVE_INTERVAL` seconds (default: 5 min) with service status information.
- The health endpoint checks both the monitor loop heartbeat and MQTT publish health — if MQTT is stale, it returns HTTP 503 so Kubernetes can restart the pod.
- If the MQTT connection fails, the service will automatically attempt to reconnect after 5 seconds.
- Debug mode (`DEBUG=True`) will use static test data instead of live API data.

---

## Logging

- Logs are output to standard output at the INFO level.
- Errors and connection issues are logged and retried automatically.

---

## Customization

- **Alert Retention:** The time an alert is kept in memory (default: 1 hour) can be changed by modifying `ALERT_TTL` in `redalert.py`.
- **Keep-Alive Interval:** Set `KEEPALIVE_INTERVAL` environment variable (default: 300 seconds).
- **Health Threshold:** The heartbeat staleness threshold (default: 30s) can be changed by modifying `HEALTH_THRESHOLD` in `redalert.py`.

---

## Troubleshooting

- **MQTT Connection Issues:** Ensure your MQTT broker is reachable and credentials are correct.
- **No Alerts Published:** Check if the Oref API is reachable and not rate-limited. Also, verify that `INCLUDE_TEST_ALERTS` is set as desired.
- **Pod Not Restarting on MQTT Failure:** Ensure your Kubernetes deployment has a liveness probe pointing to `/health` on the configured `HEALTH_PORT`. The health check will return 503 if MQTT is stale.
- **Docker Issues:** Make sure environment variables are set correctly in your Docker Compose or `docker run` command.

---

## Contributing

Feel free to open issues or submit pull requests for improvements or bug fixes.

---

## License

This project is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). See the [LICENSE](LICENSE) file for details.
