import os
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import redalert

class AsyncContextResponse:
    def __init__(self, status, text_value):
        self.status = status
        self._text_value = text_value
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        pass
    async def text(self, *args, **kwargs):
        return self._text_value

def make_awaitable_response(status, text_value):
    async def _inner(*args, **kwargs):
        return AsyncContextResponse(status, text_value)
    return _inner

@pytest.mark.asyncio
async def test_fetch_alert_success():
    session = AsyncMock()
    session.get = make_awaitable_response(200, json.dumps({'id': 1, 'data': 'alert'}))
    alert = await redalert.fetch_alert(session)
    assert alert['id'] == 1
    assert alert['data'] == 'alert'

@pytest.mark.asyncio
async def test_fetch_alert_empty():
    session = AsyncMock()
    session.get = make_awaitable_response(200, '')
    alert = await redalert.fetch_alert(session)
    assert alert is None

@pytest.mark.asyncio
async def test_fetch_alert_http_error():
    session = AsyncMock()
    session.get = make_awaitable_response(500, '')
    alert = await redalert.fetch_alert(session)
    assert alert is None

@pytest.mark.asyncio
async def test_publish_alert_success():
    mqtt_client = AsyncMock()
    alert = {'id': 1, 'data': {'msg': 'test'}}
    await redalert.publish_alert(mqtt_client, alert)
    mqtt_client.publish.assert_any_call(f"{redalert.MQTT_TOPIC}/data", json.dumps(alert['data']), qos=0)
    mqtt_client.publish.assert_any_call(f"{redalert.MQTT_TOPIC}/raw_data", json.dumps(alert), qos=0)

@pytest.mark.asyncio
async def test_publish_alert_error():
    mqtt_client = AsyncMock()
    mqtt_client.publish.side_effect = Exception('fail')
    alert = {'id': 1, 'data': {'msg': 'test'}}
    # Should not raise
    await redalert.publish_alert(mqtt_client, alert)

@pytest.mark.asyncio
async def test_monitor_handles_mqtt_error(monkeypatch):
    # Patch asyncio_mqtt.Client to be an async context manager that raises on enter
    class DummyMqttError(Exception):
        pass
    class FailingMqttClient:
        async def __aenter__(self):
            raise DummyMqttError('fail')
        async def __aexit__(self, exc_type, exc, tb):
            pass
    monkeypatch.setattr(redalert.aiomqtt, 'MqttError', DummyMqttError)
    monkeypatch.setattr(redalert.aiomqtt, 'Client', lambda *a, **kw: FailingMqttClient())
    # Patch aiohttp.ClientSession to a dummy async context manager
    class DummySession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
    monkeypatch.setattr(redalert.aiohttp, 'ClientSession', DummySession)
    # Patch asyncio.sleep to raise CancelledError after first call to break the loop
    orig_sleep = asyncio.sleep
    async def fake_sleep(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    # Should not raise (will break after first reconnect attempt)
    try:
        await redalert.monitor()
    except asyncio.CancelledError:
        pass

@pytest.mark.asyncio
async def test_fetch_alert_realistic_json():
    # This is the realistic JSON returned by the Oref API
    json_data = {
        "id": "133908130700000000",
        "cat": "10",
        "title": "בדקות הקרובות צפויות להתקבל התרעות באזורך",
        "data": ["ירושלים - מערב", "ירושלים - צפון"],
        "desc": "עליך לשפר את מיקומך למיגון המיטבי בקרבתך. במקרה של קבלת התרעה, יש להיכנס למרחב המוגן ולשהות בו 10 דקות."
    }
    session = AsyncMock()
    session.get = make_awaitable_response(200, json.dumps(json_data))
    alert = await redalert.fetch_alert(session)
    assert alert["id"] == "133908130700000000"
    assert alert["cat"] == "10"
    assert alert["title"] == "בדקות הקרובות צפויות להתקבל התרעות באזורך"
    assert alert["data"] == ["ירושלים - מערב", "ירושלים - צפון"]
    assert "desc" in alert
    assert "מרחב המוגן" in alert["desc"] 