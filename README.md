# RedAlert Relay System

The **RedAlert Relay System** is a Python-based service that fetches real-time alerts from the Israeli Oref API and relays them to MQTT topics. It is designed for reliability, supports asynchronous operation, and is easily deployable via Docker.

---

## Features

- **Fetches alerts** from the official Oref API using `aiohttp`.
- **Relays alerts** to MQTT topics using `aiomqtt` (not `asyncio-mqtt`).
- **Filters out test alerts** (configurable via `INCLUDE_TEST_ALERTS`).
- **Prevents duplicate publishing** and cleans up old alerts (1 hour retention).
- **Configurable** via environment variables.
- **Ready for Docker and Docker Compose deployment**.

---

## Requirements

- Python 3.12+ (if running locally)
- Docker (recommended for deployment)
- MQTT broker (e.g., Mosquitto)

---

## Environment Variables

| Variable              | Description                                   | Default         | Example                |
|-----------------------|-----------------------------------------------|-----------------|------------------------|
| `MQTT_HOST`           | MQTT broker address                           | 127.0.0.1       | `mqtt.example.com`     |
| `MQTT_PORT`           | MQTT broker port                              | 1883            | `1883`                 |
| `MQTT_USER`           | MQTT username                                 | user            | `myuser`               |
| `MQTT_PASS`           | MQTT password                                 | password        | `mypassword`           |
| `MQTT_TOPIC`          | Base MQTT topic for alerts                    | /redalert       | `/alerts`              |
| `INCLUDE_TEST_ALERTS` | Include test alerts (True/False)              | False           | `True`                 |
| `DEBUG`               | Enable debug mode with test data (True/False) | False           | `True`                 |

---

## MQTT Topics

- **`${MQTT_TOPIC}/data`**: Publishes the main alert data (JSON array of locations).
- **`${MQTT_TOPIC}/raw_data`**: Publishes the full raw alert payload (JSON).

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
      - INCLUDE_TEST_ALERTS=[False|True]
      - MQTT_PORT=1883
      - MQTT_TOPIC=/redalert
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
  -e DEBUG=False \
  techblog/redalert
```

---

## Running Locally (for Development)

1. **Install dependencies:**

   ```sh
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
- Alerts are tracked for 1 hour to prevent duplicate publishing (configurable via `ALERT_TTL` in `redalert.py`).
- Old alerts are cleaned up every 60 seconds.
- If the MQTT connection fails, the service will automatically attempt to reconnect after 5 seconds.
- Debug mode (`DEBUG=True`) will use static test data instead of live API data.

---

## Logging

- Logs are output to standard output at the INFO level.
- Errors and connection issues are logged and retried automatically.

---

## Customization

- **Alert Retention:** The time an alert is kept in memory (default: 1 hour) can be changed by modifying `ALERT_TTL` in `redalert.py`.
- **Polling Interval:** The script polls for new alerts every second. Adjust the `await asyncio.sleep(1)` line in `monitor()` if needed.

---

## Troubleshooting

- **MQTT Connection Issues:** Ensure your MQTT broker is reachable and credentials are correct.
- **No Alerts Published:** Check if the Oref API is reachable and not rate-limited. Also, verify that `INCLUDE_TEST_ALERTS` is set as desired.
- **Docker Issues:** Make sure environment variables are set correctly in your Docker Compose or `docker run` command.

---

## Contributing

Feel free to open issues or submit pull requests for improvements or bug fixes.

---

## License

This project is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). See the [LICENSE](LICENSE) file for details.

---

**This documentation is auto-generated based on the current code and deployment files. For updates, always refer to the latest codebase.**
