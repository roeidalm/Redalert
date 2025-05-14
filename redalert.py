#!/usr/bin/env python
# -*- coding: utf-8 -*-
import asyncio
import aiohttp
import os
import json
import logging
import aiomqtt
import time

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
logger.info(f"Monitoring alerts, sending to topic: {MQTT_TOPIC}")

_headers = {
    'Referer': 'https://www.oref.org.il/',
    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.97 Safari/537.36",
    'X-Requested-With': 'XMLHttpRequest'
}
url = 'https://www.oref.org.il/WarningMessages/alert/alerts.json'

DEBUG_ALERT_DATA="{\"id\":\"133908130700000000\",\"cat\":\"10\",\"title\":\"בדקות הקרובות צפויות להתקבל התרעות באזורך\",\"data\":[\"ירושלים - מערב\",\"ירושלים - צפון\"],\"desc\":\"עליך לשפר את מיקומך למיגון המיטבי בקרבתך. במקרה של קבלת התרעה, יש להיכנס למרחב המוגן ולשהות בו 10 דקות.\"}"

# Replace alerts set with a dict for time-based cleanup
alerts = {}
ALERT_TTL = 3600  # 1 hour in seconds

def is_test_alert(alert):
    return INCLUDE_TEST_ALERTS == 'False' and ('בדיקה' in alert.get('data', '') or 'בדיקה מחזורית' in alert.get('data', ''))

async def fetch_alert(session: aiohttp.ClientSession):
    try:
        async with await session.get(url, headers=_headers) as response:
            if response.status != 200:
                logger.warning(f"Failed to fetch alerts: HTTP {response.status}")
                return None
            alert_data = await response.text(encoding='utf-8-sig')
            if IS_DEBUG == "True":
                alert_data=DEBUG_ALERT_DATA
            if len(alert_data) < 5 or not alert_data or alert_data.isspace():
                return None
            alert = json.loads(alert_data)
            logger.info("Alert data successfully parsed.")
            return alert
    except json.JSONDecodeError as jde:
        logger.error(f"Failed to parse JSON: {jde}, raw data: {alert_data[:100]}...")
        return None
    except Exception as ex:
        logger.error(f"Exception during fetch_alert: {ex}")
        return None

async def publish_alert(mqtt_client, alert):
    try:
        # Publish the data section
        await mqtt_client.publish(f"{MQTT_TOPIC}/data", json.dumps(alert.get('data', {})), qos=0)
        # Publish the full raw alert
        await mqtt_client.publish(f"{MQTT_TOPIC}/raw_data", json.dumps(alert), qos=0)
        logger.info("Alert published to MQTT topics.")
    except Exception as e:
        logger.error(f"Failed to publish alert to MQTT: {e}")

def cleanup_alerts():
    now = time.time()
    to_remove = [aid for aid, ts in alerts.items() if now - ts > ALERT_TTL]
    for aid in to_remove:
        del alerts[aid]

async def monitor():
    async with aiohttp.ClientSession() as session:
        reconnect_interval = 5
        last_cleanup = time.time()
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=server,
                    port=port,
                    username=user,
                    password=passw,
                ) as mqtt_client:
                    logger.info("Connected to MQTT broker.")
                    while True:
                        alert = await fetch_alert(session)
                        if alert and alert.get("id") not in alerts and not is_test_alert(alert):
                            alerts[alert["id"]] = time.time()
                            logger.info(f"New alert: {alert}")
                            await publish_alert(mqtt_client, alert)
                        # Cleanup every 60 seconds
                        if time.time() - last_cleanup > 60:
                            cleanup_alerts()
                            last_cleanup = time.time()
                        await asyncio.sleep(1)
            except aiomqtt.MqttError as me:
                logger.error(f"MQTT error: {me}. Reconnecting in {reconnect_interval} seconds...")
                await asyncio.sleep(reconnect_interval)
            except Exception as ex:
                logger.error(f"Unexpected error: {ex}. Reconnecting in {reconnect_interval} seconds...")
                await asyncio.sleep(reconnect_interval)

if __name__ == '__main__':
    asyncio.run(monitor())
