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
import pathlib
from dataclasses import dataclass, asdict
from typing import List, Optional
from shapely.geometry import Point, Polygon

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
KEEPALIVE_INTERVAL = int(os.getenv("KEEPALIVE_INTERVAL", 300))  # default 5 min
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
last_successful_fetch: float = 0.0
last_mqtt_success: float = 0.0

# Area endpoint configuration
AREA_POLYGONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "area_polygons.json")
AREA_REFRESH_INTERVAL = 86400  # 24 hours in seconds
AREA_FETCH_CONCURRENCY = 20
OREF_CITIES_URL = "https://alerts-history.oref.org.il/Shared/Ajax/GetCitiesMix.aspx"
MESER_SEGMENTS_URL = "https://dist-android.meser-hadash.org.il/smart-dist/services/anonymous/segments/android?instance=1544803905&locale=iw_IL"
MESER_POLYGON_URL_TEMPLATE = "https://services.meser-hadash.org.il/smart-dist/services/anonymous/polygon/id/android?instance=1544803905&id={segment_id}"

# In-memory bounding box index: {"city_name": {"migun_time": int, "bbox": (min_lat, max_lat, min_lon, max_lon)}}
area_bbox_index: dict = {}
area_data_loaded: bool = False


def is_test_alert(alert: AlertObject) -> bool:
    return INCLUDE_TEST_ALERTS == 'False' and ('בדיקה' in alert.data or 'בדיקה מחזורית' in alert.data)


async def fetch_alert(session: aiohttp.ClientSession) -> Optional[AlertObject]:
    global last_successful_fetch
    try:
        async with await session.get(url, headers=_headers) as response:
            if response.status != 200:
                logger.warning(f"Failed to fetch alerts: HTTP {response.status}")
                return None

            last_successful_fetch = time.time()
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
    global last_mqtt_success
    try:
        # Publish the data section
        await mqtt_client.publish(f"{MQTT_TOPIC}/cat/{alert.cat}", json.dumps({"title": alert.title, "data": alert.data, "desc": alert.desc}, ensure_ascii=False), qos=0)
        # Publish the full raw alert
        await mqtt_client.publish(f"{MQTT_TOPIC}/raw_data", alert.raw_data, qos=0)
        last_mqtt_success = time.time()
        logger.info("Alert published to MQTT topics.")
    except Exception as e:
        logger.error(f"Failed to publish alert to MQTT: {e}")

def cleanup_alerts():
    now = time.time()
    to_remove = [aid for aid, ts in alerts.items() if now - ts > ALERT_TTL]
    for aid in to_remove:
        del alerts[aid]


def _area_file_is_fresh() -> bool:
    p = pathlib.Path(AREA_POLYGONS_FILE)
    if not p.exists():
        return False
    age = time.time() - p.stat().st_mtime
    return age < AREA_REFRESH_INTERVAL


async def fetch_area_polygons(session: aiohttp.ClientSession) -> dict:
    logger.info("Starting area polygon data fetch...")
    try:
        # Step 1: Fetch city list from Pikud Haoref
        async with await session.get(OREF_CITIES_URL) as resp:
            if resp.status != 200:
                logger.error(f"Failed to fetch cities: HTTP {resp.status}")
                return {}
            cities_data = await resp.json(content_type=None)

        city_map = {}
        for city in cities_data:
            label = city.get("label", "").strip()
            migun_time = city.get("migun_time", "0")
            if label:
                city_map[label] = int(migun_time) if str(migun_time).isdigit() else 0

        logger.info(f"Fetched {len(city_map)} cities from Oref")

        # Step 2: Fetch segments from meser-hadash
        async with await session.get(MESER_SEGMENTS_URL) as resp:
            if resp.status != 200:
                logger.error(f"Failed to fetch segments: HTTP {resp.status}")
                return {}
            segments_data = await resp.json(content_type=None)

        segments = segments_data.get("segments", {})
        # Build name -> segment_id mapping
        segment_by_name = {}
        for seg_id, seg in segments.items():
            name = seg.get("name", "").strip()
            if name:
                segment_by_name[name] = seg.get("id", seg_id)

        # Step 3: Match cities to segments and fetch polygons
        matched = []
        for city_name, migun_time in city_map.items():
            if city_name in segment_by_name:
                matched.append((city_name, migun_time, segment_by_name[city_name]))

        logger.info(f"Matched {len(matched)} cities to segments")

        result = {}
        sem = asyncio.Semaphore(AREA_FETCH_CONCURRENCY)

        async def fetch_polygon(city_name, migun_time, segment_id):
            async with sem:
                try:
                    poly_url = MESER_POLYGON_URL_TEMPLATE.format(segment_id=segment_id)
                    async with await session.get(poly_url) as resp:
                        if resp.status != 200:
                            return
                        poly_data = await resp.json(content_type=None)
                    point_list = poly_data.get("polygonPointList", [])
                    if point_list and len(point_list) > 0:
                        polygon = point_list[0] if isinstance(point_list[0][0], list) else point_list
                        result[city_name] = {"migun_time": migun_time, "polygon": polygon}
                except Exception as e:
                    logger.warning(f"Failed to fetch polygon for {city_name}: {e}")

        tasks = [fetch_polygon(cn, mt, sid) for cn, mt, sid in matched]
        await asyncio.gather(*tasks)

        logger.info(f"Area polygon fetch complete. Total areas: {len(result)}")
        return result
    except Exception as e:
        logger.error(f"Error fetching area polygons: {e}")
        return {}


def build_bbox_index(area_data: dict) -> dict:
    index = {}
    for name, data in area_data.items():
        polygon = data.get("polygon", [])
        if not polygon:
            continue
        lats = [p[0] for p in polygon]
        lons = [p[1] for p in polygon]
        index[name] = {
            "migun_time": data.get("migun_time", 0),
            "bbox": (min(lats), max(lats), min(lons), max(lons))
        }
    return index


async def load_area_data():
    global area_bbox_index, area_data_loaded

    if _area_file_is_fresh():
        logger.info("Loading area data from fresh file...")
        try:
            with open(AREA_POLYGONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            area_bbox_index = build_bbox_index(data)
            area_data_loaded = True
            logger.info(f"Loaded {len(area_bbox_index)} areas from file")
            return
        except Exception as e:
            logger.error(f"Failed to load area file: {e}")

    # File missing or stale — fetch fresh data
    logger.info("Fetching fresh area data...")
    timeout = aiohttp.ClientTimeout(sock_connect=10, sock_read=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch_area_polygons(session)
    except Exception as e:
        logger.error(f"Failed to create session for area fetch: {e}")
        data = {}

    if data:
        try:
            with open(AREA_POLYGONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            area_bbox_index = build_bbox_index(data)
            area_data_loaded = True
            logger.info(f"Saved and indexed {len(area_bbox_index)} areas")
            return
        except Exception as e:
            logger.error(f"Failed to save area file: {e}")

    # Fetch failed — try stale file as fallback
    if pathlib.Path(AREA_POLYGONS_FILE).exists():
        logger.warning("Fetch failed, falling back to stale area file")
        try:
            with open(AREA_POLYGONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            area_bbox_index = build_bbox_index(data)
            area_data_loaded = True
            logger.info(f"Loaded {len(area_bbox_index)} areas from stale file")
            return
        except Exception as e:
            logger.error(f"Failed to load stale area file: {e}")

    logger.error("No area data available")
    area_data_loaded = False


async def area_refresh_loop():
    while True:
        try:
            await asyncio.sleep(AREA_REFRESH_INTERVAL)
            await load_area_data()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error in area refresh loop: {e}")


def lookup_area(lat: float, lon: float) -> Optional[dict]:
    # Pre-filter candidates using bounding box
    candidates = []
    for name, info in area_bbox_index.items():
        min_lat, max_lat, min_lon, max_lon = info["bbox"]
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            candidates.append((name, info["migun_time"]))

    if not candidates:
        return None

    # Load polygons from file and check containment
    try:
        with open(AREA_POLYGONS_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
    except Exception:
        return None

    point = Point(lon, lat)
    for name, migun_time in candidates:
        area_entry = all_data.get(name)
        if not area_entry:
            continue
        poly_coords = area_entry.get("polygon", [])
        if len(poly_coords) < 3:
            continue
        # File stores [lat, lon], shapely needs (x=lon, y=lat)
        shapely_coords = [(p[1], p[0]) for p in poly_coords]
        polygon = Polygon(shapely_coords)
        if polygon.contains(point):
            return {"area": name, "migun_time": migun_time}

    return None


async def area_handler(request):
    lat_str = request.query.get("lat")
    lon_str = request.query.get("lon")

    if not lat_str or not lon_str:
        return aiohttp.web.json_response(
            {"error": "Missing or invalid lat/lon query parameters"}, status=400
        )
    try:
        lat = float(lat_str)
        lon = float(lon_str)
    except ValueError:
        return aiohttp.web.json_response(
            {"error": "Missing or invalid lat/lon query parameters"}, status=400
        )

    if not area_data_loaded:
        return aiohttp.web.json_response(
            {"error": "Area data not loaded yet"}, status=503
        )

    result = lookup_area(lat, lon)
    if result:
        return aiohttp.web.json_response(result, status=200)

    return aiohttp.web.json_response(
        {"error": "No alert area found for given coordinates"}, status=404
    )


async def health_handler(request):
    now = time.time()
    age = now - last_heartbeat
    if last_heartbeat == 0 or age > HEALTH_THRESHOLD:
        return aiohttp.web.json_response(
            {"status": "frozen", "last_heartbeat_ago": round(age, 1)}, status=503
        )
    # Check MQTT health — allow startup grace period (KEEPALIVE_INTERVAL + 60s)
    mqtt_grace = KEEPALIVE_INTERVAL + 60
    mqtt_age = now - last_mqtt_success
    if last_mqtt_success == 0 and age > mqtt_grace:
        return aiohttp.web.json_response(
            {"status": "mqtt_stale", "last_heartbeat_ago": round(age, 1), "last_mqtt_ago": None}, status=503
        )
    if last_mqtt_success > 0 and mqtt_age > mqtt_grace:
        return aiohttp.web.json_response(
            {"status": "mqtt_stale", "last_heartbeat_ago": round(age, 1), "last_mqtt_ago": round(mqtt_age, 1)}, status=503
        )
    return aiohttp.web.json_response(
        {"status": "ok", "last_heartbeat_ago": round(age, 1)}, status=200
    )


async def run_health_server():
    app = aiohttp.web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/area", area_handler)
    runner = aiohttp.web.AppRunner(app, access_log=None)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "0.0.0.0", HEALTH_PORT)
    await site.start()
    logger.info(f"Health endpoint listening on port {HEALTH_PORT}")
    while True:
        await asyncio.sleep(3600)


async def monitor():
    global last_heartbeat
    poll_interval = 1  # seconds between poll cycles
    fetch_timeout = 4  # max seconds for a single fetch attempt
    timeout = aiohttp.ClientTimeout(sock_connect=3, sock_read=3)
    connector = aiohttp.TCPConnector(
        limit=5,
        ttl_dns_cache=60,
        enable_cleanup_closed=True,
    )
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
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
                    start_time = time.time()
                    last_keepalive = start_time
                    while True:
                        cycle_start = time.monotonic()
                        try:
                            alert = await asyncio.wait_for(
                                fetch_alert(session), timeout=fetch_timeout
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"fetch_alert timed out after {fetch_timeout}s")
                            alert = None
                        if alert and alert.id not in alerts and not is_test_alert(alert):
                            alerts[alert.id] = time.time()
                            logger.info(f"New alert: {alert.raw_data.replace(chr(10), '').replace(chr(13), '').replace('  ', ' ')}")
                            await publish_alert(mqtt_client, alert)
                        # Cleanup every 60 seconds
                        if time.time() - last_cleanup > 60:
                            cleanup_alerts()
                            last_cleanup = time.time()
                        # Fixed-rate polling: sleep only the remaining time
                        elapsed = time.monotonic() - cycle_start
                        remaining = poll_interval - elapsed
                        if remaining > 0:
                            await asyncio.sleep(remaining)
                        last_heartbeat = time.time()
                        # Keep-alive publish
                        if time.time() - last_keepalive >= KEEPALIVE_INTERVAL:
                            await mqtt_client.publish(
                                f"{MQTT_TOPIC}/keepalive",
                                json.dumps({
                                    "status": "online",
                                    "mqtt": "connected",
                                    "oref": "ok" if (time.time() - last_successful_fetch) < 30 else "failing",
                                    "uptime": round(time.time() - start_time),
                                    "timestamp": round(time.time()),
                                }),
                                qos=0,
                            )
                            last_mqtt_success = time.time()
                            last_keepalive = time.time()
                            logger.info("Keep-alive published to MQTT")
            except aiomqtt.MqttError as me:
                logger.error(f"MQTT error: {me}. Reconnecting in {reconnect_interval} seconds...")
                await asyncio.sleep(reconnect_interval)
            except Exception as ex:
                logger.error(f"Unexpected error: {ex}. Reconnecting in {reconnect_interval} seconds...")
                await asyncio.sleep(reconnect_interval)

if __name__ == '__main__':
    async def main():
        await load_area_data()
        await asyncio.gather(monitor(), run_health_server(), area_refresh_loop())
    asyncio.run(main())
