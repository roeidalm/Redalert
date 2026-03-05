#!/usr/bin/env python
# -*- coding: utf-8 -*-
import asyncio
import aiohttp
import aiohttp.web
import os
import json
import logging
import aiomqtt
import time
from dataclasses import dataclass, asdict
from typing import List, Optional

@dataclass
class AlertObject:
    id: str
    cat: str
    title: str
    data: List[str]
    desc: str
    raw_data: str

os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['LANG'] = 'C.UTF-8'

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("redalert")

# MQTT connection Params
server = os.getenv('MQTT_HOST', "127.0.0.1")
port = int(os.getenv('MQTT_PORT', 1883))
user = os.getenv('MQTT_USER', 'user')
passw = os.getenv('MQTT_PASS', 'password')
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "/redalert")
INCLUDE_TEST_ALERTS = os.getenv("INCLUDE_TEST_ALERTS", "False")
IS_DEBUG = os.getenv("DEBUG", "False")
HEALTH_PORT = int(os.getenv("HEALTH_PORT", 8080))
HEALTH_THRESHOLD = 30  # seconds of silence before considered frozen
logger.info(f"Monitoring alerts, sending to topic: {MQTT_TOPIC}")

_headers = {
    'Referer': 'https://www.oref.org.il/',
    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.97 Safari/537.36",
    'X-Requested-With': 'XMLHttpRequest'
}
url = 'https://www.oref.org.il/WarningMessages/alert/alerts.json'

index = 0
DEBUG_ALERT_DATA = {
    "id": "133908130700000000",
    "cat": "10",
    "title": "בדקות הקרובות צפויות להתקבל התרעות באזורך",
    "data": ["ירושלים - מערב", "ירושלים - צפון"],
    "desc": "עליך לשפר את מיקומך למיגון המיטבי בקרבתך. במקרה של קבלת התרעה, יש להיכנס למרחב המוגן ולשהות בו 10 דקות."
}

# Replace alerts set with a dict for time-based cleanup
alerts = {}
ALERT_TTL = 3600  # 1 hour in seconds
last_heartbeat: float = 0.0


def is_test_alert(alert: AlertObject) -> bool:
    return INCLUDE_TEST_ALERTS == 'False' and ('בדיקה' in alert.data or 'בדיקה מחזורית' in alert.data)


async def fetch_alert(session: aiohttp.ClientSession) -> Optional[AlertObject]:
    try:
        async with await session.get(url, headers=_headers) as response:
            if response.status != 200:
                logger.warning(f"Failed to fetch alerts: HTTP {response.status}")
                return None

            alert_data = await response.text(encoding='utf-8-sig')
            alert_data = alert_data.replace('\x00', '').strip()
            
            if IS_DEBUG == "True":
                global index
                index += 1
                DEBUG_ALERT_DATA["id"] = str(index)
                alert_data = json.dumps(DEBUG_ALERT_DATA, ensure_ascii=False)
                
            if not alert_data or alert_data.isspace():
                return None

            alert = json.loads(alert_data)
            # Convert alert data to dataclass
            alert_object = AlertObject(
                id=alert.get("id", f"random-id-{time.time()}"),
                cat=alert.get("cat", "-1"),
                title=alert.get("title", "unknown"),
                data=alert.get("data", []),
                desc=alert.get("desc", "unknown"),
                raw_data=alert_data
            )
            logger.debug("Alert data successfully parsed.")
            return alert_object
    except json.JSONDecodeError as jde:
        logger.error(f"Failed to parse JSON: {jde}")
        return None
    except Exception as ex:
        logger.error(f"Exception during fetch_alert: {ex}")
        return None


async def publish_alert(mqtt_client: aiomqtt.Client, alert: AlertObject):
    try:
        # Publish the data section
        await mqtt_client.publish(f"{MQTT_TOPIC}/cat/{alert.cat}", json.dumps({"title": alert.title, "data": alert.data, "desc": alert.desc}, ensure_ascii=False), qos=0)
        # Publish the full raw alert
        await mqtt_client.publish(f"{MQTT_TOPIC}/raw_data", alert.raw_data, qos=0)
        logger.info("Alert published to MQTT topics.")
    except Exception as e:
        logger.error(f"Failed to publish alert to MQTT: {e}")

def cleanup_alerts():
    now = time.time()
    to_remove = [aid for aid, ts in alerts.items() if now - ts > ALERT_TTL]
    for aid in to_remove:
        del alerts[aid]

async def health_handler(request):
    age = time.time() - last_heartbeat
    if last_heartbeat == 0 or age > HEALTH_THRESHOLD:
        return aiohttp.web.json_response(
            {"status": "frozen", "last_heartbeat_ago": round(age, 1)}, status=503
        )
    return aiohttp.web.json_response(
        {"status": "ok", "last_heartbeat_ago": round(age, 1)}, status=200
    )


async def run_health_server():
    app = aiohttp.web.Application()
    app.router.add_get("/health", health_handler)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "0.0.0.0", HEALTH_PORT)
    await site.start()
    logger.info(f"Health endpoint listening on port {HEALTH_PORT}")
    while True:
        await asyncio.sleep(3600)


async def monitor():
    global last_heartbeat
    timeout = aiohttp.ClientTimeout(sock_connect=5, sock_read=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        reconnect_interval = 5
        last_cleanup = time.time()
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=server,
                    port=port,
                    username=user,
                    password=passw,
                    timeout=10,
                ) as mqtt_client:
                    logger.info("Connected to MQTT broker.")
                    while True:
                        alert = await fetch_alert(session)
                        if alert and alert.id not in alerts and not is_test_alert(alert):
                            alerts[alert.id] = time.time()
                            logger.info(f"New alert: {alert.raw_data.replace(chr(10), '').replace(chr(13), '').replace('  ', ' ')}")
                            await publish_alert(mqtt_client, alert)
                        # Cleanup every 60 seconds
                        if time.time() - last_cleanup > 60:
                            cleanup_alerts()
                            last_cleanup = time.time()
                        await asyncio.sleep(1)
                        last_heartbeat = time.time()
            except aiomqtt.MqttError as me:
                logger.error(f"MQTT error: {me}. Reconnecting in {reconnect_interval} seconds...")
                await asyncio.sleep(reconnect_interval)
            except Exception as ex:
                logger.error(f"Unexpected error: {ex}. Reconnecting in {reconnect_interval} seconds...")
                await asyncio.sleep(reconnect_interval)

if __name__ == '__main__':
    async def main():
        await asyncio.gather(monitor(), run_health_server())
    asyncio.run(main())
