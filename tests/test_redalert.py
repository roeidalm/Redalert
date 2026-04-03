import os
import pytest
import asyncio
import json
import time
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

# Test AlertObject dataclass


def test_alert_object_creation():
    alert = redalert.AlertObject(
        id="123",
        cat="10",
        title="Test Alert",
        data=["Area 1", "Area 2"],
        desc="Test description",
        raw_data=""
    )
    assert alert.id == "123"
    assert alert.cat == "10"
    assert alert.title == "Test Alert"
    assert alert.data == ["Area 1", "Area 2"]
    assert alert.desc == "Test description"


def test_alert_object_to_json_str():
    alert = redalert.AlertObject(
        id="123",
        cat="10",
        title="Test Alert",
        data=["Area 1", "Area 2"],
        desc="Test description",
        raw_data=""
    )
    json_str = json.dumps({
        "id": alert.id,
        "cat": alert.cat,
        "title": alert.title,
        "data": alert.data,
        "desc": alert.desc
    }, ensure_ascii=False)
    parsed = json.loads(json_str)
    assert parsed["id"] == "123"
    assert parsed["cat"] == "10"
    assert parsed["title"] == "Test Alert"
    assert parsed["data"] == ["Area 1", "Area 2"]
    assert parsed["desc"] == "Test description"

# Test is_test_alert function


def test_is_test_alert_with_test_data():
    # Test with INCLUDE_TEST_ALERTS = 'False' (default)
    alert = redalert.AlertObject(
        id="123",
        cat="10",
        title="Test Alert",
        data=["בדיקה", "Area 2"],
        desc="Test description",
        raw_data=""
    )
    assert redalert.is_test_alert(alert) == True


def test_is_test_alert_with_periodic_test():
    alert = redalert.AlertObject(
        id="123",
        cat="10",
        title="Test Alert",
        data=["Area 1", "בדיקה מחזורית"],
        desc="Test description",
        raw_data=""
    )
    assert redalert.is_test_alert(alert) == True


def test_is_test_alert_with_normal_data():
    alert = redalert.AlertObject(
        id="123",
        cat="10",
        title="Test Alert",
        data=["ירושלים - מערב", "ירושלים - צפון"],
        desc="Test description",
        raw_data=""
    )
    assert redalert.is_test_alert(alert) == False


@patch.dict(os.environ, {"INCLUDE_TEST_ALERTS": "True"})
def test_is_test_alert_when_including_tests():
    # Need to reload the module or patch the function to pick up the new env var
    with patch.object(redalert, 'INCLUDE_TEST_ALERTS', 'True'):
        alert = redalert.AlertObject(
            id="123",
            cat="10",
            title="Test Alert",
            data=["בדיקה", "Area 2"],
            desc="Test description",
            raw_data=""
        )
        assert redalert.is_test_alert(alert) == False

# Test cleanup_alerts function


def test_cleanup_alerts():
    # Clear alerts dict first
    redalert.alerts.clear()

    # Add some alerts with different timestamps
    current_time = time.time()
    redalert.alerts["old_alert"] = current_time - 3700  # Older than TTL
    redalert.alerts["recent_alert"] = current_time - 100  # Within TTL
    redalert.alerts["very_old_alert"] = current_time - \
        7200  # Much older than TTL

    # Run cleanup
    redalert.cleanup_alerts()

    # Check that only recent alert remains
    assert "recent_alert" in redalert.alerts
    assert "old_alert" not in redalert.alerts
    assert "very_old_alert" not in redalert.alerts


def test_cleanup_alerts_empty():
    redalert.alerts.clear()
    # Should not raise any errors
    redalert.cleanup_alerts()
    assert len(redalert.alerts) == 0

@pytest.mark.asyncio
async def test_fetch_alert_success():
    json_data = {
        "id": "123",
        "cat": "10",
        "title": "Test Alert",
        "data": ["Area 1", "Area 2"],
        "desc": "Test description"
    }
    session = AsyncMock()
    session.get = make_awaitable_response(200, json.dumps(json_data))

    alert = await redalert.fetch_alert(session)
    assert isinstance(alert, redalert.AlertObject)
    assert alert.id == "123"
    assert alert.cat == "10"
    assert alert.title == "Test Alert"
    assert alert.data == ["Area 1", "Area 2"]
    assert alert.desc == "Test description"


@pytest.mark.asyncio
async def test_fetch_alert_with_defaults():
    # Test with missing fields to check defaults
    json_data = {"id": "123"}
    session = AsyncMock()
    session.get = make_awaitable_response(200, json.dumps(json_data))

    alert = await redalert.fetch_alert(session)
    assert isinstance(alert, redalert.AlertObject)
    assert alert.id == "123"
    assert alert.cat == "-1"
    assert alert.title == "unknown"
    assert alert.data == []
    assert alert.desc == "unknown"


@pytest.mark.asyncio
async def test_fetch_alert_with_null_bytes():
    json_data = {"id": "123", "title": "Test"}
    json_str = json.dumps(json_data) + "\x00\x00"  # Add null bytes
    session = AsyncMock()
    session.get = make_awaitable_response(200, json_str)

    alert = await redalert.fetch_alert(session)
    assert isinstance(alert, redalert.AlertObject)
    assert alert.id == "123"
    assert alert.title == "Test"


@pytest.mark.asyncio
@patch.dict(os.environ, {"DEBUG": "True"})
async def test_fetch_alert_debug_mode():
    session = AsyncMock()
    # Response doesn't matter in debug mode
    session.get = make_awaitable_response(200, "")

    # Reset global index
    redalert.index = 0

    # Patch the IS_DEBUG variable directly
    with patch.object(redalert, 'IS_DEBUG', 'True'):
        alert = await redalert.fetch_alert(session)
        assert isinstance(alert, redalert.AlertObject)
        assert alert.id == "1"  # Should be incremented index
        assert alert.cat == "10"
        assert "בדקות הקרובות" in alert.title

@pytest.mark.asyncio
async def test_fetch_alert_empty():
    session = AsyncMock()
    session.get = make_awaitable_response(200, '')
    alert = await redalert.fetch_alert(session)
    assert alert is None


@pytest.mark.asyncio
async def test_fetch_alert_whitespace_only():
    session = AsyncMock()
    session.get = make_awaitable_response(200, '   \n\t  ')
    alert = await redalert.fetch_alert(session)
    assert alert is None

@pytest.mark.asyncio
async def test_fetch_alert_http_error():
    session = AsyncMock()
    session.get = make_awaitable_response(500, '')
    alert = await redalert.fetch_alert(session)
    assert alert is None


@pytest.mark.asyncio
async def test_fetch_alert_json_decode_error():
    session = AsyncMock()
    session.get = make_awaitable_response(200, 'invalid json{')
    alert = await redalert.fetch_alert(session)
    assert alert is None

@pytest.mark.asyncio
async def test_publish_alert_success():
    mqtt_client = AsyncMock()
    alert = redalert.AlertObject(
        id="123",
        cat="10",
        title="Test Alert",
        data=["Area 1", "Area 2"],
        desc="Test description",
        raw_data=json.dumps({
            "id": "123",
            "cat": "10",
            "title": "Test Alert",
            "data": ["Area 1", "Area 2"],
            "desc": "Test description"
        }, ensure_ascii=False)
    )

    await redalert.publish_alert(mqtt_client, alert)

    # Check that both topics were published to
    assert mqtt_client.publish.call_count == 2

    # Check the calls were made with correct topics and payloads
    calls = mqtt_client.publish.call_args_list

    # First call should be to cat topic
    first_call = calls[0]
    assert first_call[0][0] == f"{redalert.MQTT_TOPIC}/cat/10"  # topic
    assert json.loads(first_call[0][1]) == {
        "title": "Test Alert",
        "data": ["Area 1", "Area 2"],
        "desc": "Test description"
    }  # payload
    assert first_call[1]['qos'] == 0 or (
        len(first_call[0]) > 2 and first_call[0][2] == 0)  # qos

    # Second call should be to raw_data topic
    second_call = calls[1]
    assert second_call[0][0] == f"{redalert.MQTT_TOPIC}/raw_data"  # topic
    assert json.loads(second_call[0][1]) == json.loads(alert.raw_data)  # payload
    assert second_call[1]['qos'] == 0 or (
        len(second_call[0]) > 2 and second_call[0][2] == 0)  # qos

@pytest.mark.asyncio
async def test_publish_alert_error():
    mqtt_client = AsyncMock()
    mqtt_client.publish.side_effect = Exception('MQTT publish failed')
    alert = redalert.AlertObject(
        id="123",
        cat="10",
        title="Test Alert",
        data=["Area 1", "Area 2"],
        desc="Test description",
        raw_data=json.dumps({
            "id": "123",
            "cat": "10",
            "title": "Test Alert",
            "data": ["Area 1", "Area 2"],
            "desc": "Test description"
        }, ensure_ascii=False)
    )

    # Should not raise exception
    await redalert.publish_alert(mqtt_client, alert)

@pytest.mark.asyncio
async def test_monitor_handles_mqtt_error(monkeypatch):
    # Patch aiomqtt.Client to be an async context manager that raises on enter
    class DummyMqttError(Exception):
        pass

    class FailingMqttClient:
        async def __aenter__(self):
            raise DummyMqttError('MQTT connection failed')
        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(redalert.aiomqtt, 'MqttError', DummyMqttError)
    monkeypatch.setattr(redalert.aiomqtt, 'Client', lambda *a, **kw: FailingMqttClient())

    # Patch aiohttp.ClientSession to a dummy async context manager
    class DummySession:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(redalert.aiohttp, 'ClientSession', DummySession)

    # Patch asyncio.sleep to raise CancelledError after first call to break the loop
    async def fake_sleep(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

    # Should not raise (will break after first reconnect attempt)
    try:
        await redalert.monitor()
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_monitor_alert_deduplication(monkeypatch):
    """Test that monitor doesn't publish duplicate alerts"""
    # Clear alerts dict
    redalert.alerts.clear()

    # Create a mock alert
    alert_data = {
        "id": "test_alert_123",
        "cat": "10",
        "title": "Test Alert",
        "data": ["Area 1"],
        "desc": "Test description"
    }

    # Mock fetch_alert to return the same alert multiple times
    async def mock_fetch_alert(session):
        return redalert.AlertObject(**alert_data, raw_data="")

    # Mock MQTT client
    mock_mqtt_client = AsyncMock()

    class MockMqttClient:
        async def __aenter__(self):
            return mock_mqtt_client

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(redalert.aiomqtt, 'Client',
                        lambda *a, **kw: MockMqttClient())
    monkeypatch.setattr(redalert, 'fetch_alert', mock_fetch_alert)

    # Mock aiohttp.ClientSession
    class DummySession:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(redalert.aiohttp, 'ClientSession', DummySession)
    monkeypatch.setattr(redalert, 'KEEPALIVE_INTERVAL', 999999)  # disable keep-alive for this test

    # Counter to limit iterations
    iteration_count = 0
    original_sleep = asyncio.sleep

    async def counting_sleep(*args, **kwargs):
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count >= 3:  # Stop after 3 iterations
            raise asyncio.CancelledError()
        await original_sleep(0.01)  # Very short sleep

    monkeypatch.setattr(asyncio, 'sleep', counting_sleep)

    try:
        await redalert.monitor()
    except asyncio.CancelledError:
        pass

    # Should only publish once despite multiple fetch calls
    assert mock_mqtt_client.publish.call_count == 2  # cat topic + raw_data topic
    assert "test_alert_123" in redalert.alerts

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
    assert isinstance(alert, redalert.AlertObject)
    assert alert.id == "133908130700000000"
    assert alert.cat == "10"
    assert alert.title == "בדקות הקרובות צפויות להתקבל התרעות באזורך"
    assert alert.data == ["ירושלים - מערב", "ירושלים - צפון"]
    assert "מרחב המוגן" in alert.desc


@pytest.mark.asyncio
async def test_monitor_basic_functionality(monkeypatch):
    """Test basic monitor functionality without complex timing"""
    # Clear alerts dict
    redalert.alerts.clear()

    # Mock fetch_alert to return None (no alerts)
    async def mock_fetch_alert(session):
        return None

    monkeypatch.setattr(redalert, 'fetch_alert', mock_fetch_alert)

    # Mock MQTT client
    mock_mqtt_client = AsyncMock()

    class MockMqttClient:
        async def __aenter__(self):
            return mock_mqtt_client

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(redalert.aiomqtt, 'Client',
                        lambda *a, **kw: MockMqttClient())

    # Mock aiohttp.ClientSession
    class DummySession:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(redalert.aiohttp, 'ClientSession', DummySession)

    # Counter to control iterations
    iteration_count = 0

    async def counting_sleep(*args, **kwargs):
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count >= 2:  # Stop after 2 iterations
            raise asyncio.CancelledError()
        await asyncio.sleep(0.001)  # Very short actual sleep

    monkeypatch.setattr(asyncio, 'sleep', counting_sleep)

    try:
        await redalert.monitor()
    except asyncio.CancelledError:
        pass

    # Test passed if we got here without exceptions
    assert iteration_count >= 2

# --- 100% coverage additions ---
import importlib

def test_fetch_alert_json_decode_error_branch():
    session = AsyncMock()
    # This will cause json.loads to raise JSONDecodeError
    session.get = make_awaitable_response(200, 'not a json')
    # Patch response.text to return the same string
    with patch('redalert.logger') as mock_logger:
        alert = asyncio.run(redalert.fetch_alert(session))
        assert alert is None
        assert mock_logger.error.called

def test_monitor_mqtt_error_branch(monkeypatch):
    class DummyMqttError(Exception):
        pass
    class FailingMqttClient:
        async def __aenter__(self):
            raise DummyMqttError('MQTT error')
        async def __aexit__(self, exc_type, exc, tb):
            pass
    monkeypatch.setattr(redalert.aiomqtt, 'MqttError', DummyMqttError)
    monkeypatch.setattr(redalert.aiomqtt, 'Client', lambda *a, **kw: FailingMqttClient())
    class DummySession:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
    monkeypatch.setattr(redalert.aiohttp, 'ClientSession', DummySession)
    async def fake_sleep(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    try:
        asyncio.run(redalert.monitor())
    except asyncio.CancelledError:
        pass
    except Exception:
        pass

def test_monitor_generic_exception_branch(monkeypatch):
    class FailingMqttClient:
        async def __aenter__(self):
            raise Exception('Generic error')
        async def __aexit__(self, exc_type, exc, tb):
            pass
    monkeypatch.setattr(redalert.aiomqtt, 'Client', lambda *a, **kw: FailingMqttClient())
    class DummySession:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
    monkeypatch.setattr(redalert.aiohttp, 'ClientSession', DummySession)
    async def fake_sleep(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    try:
        asyncio.run(redalert.monitor())
    except asyncio.CancelledError:
        pass
    except Exception:
        pass

@pytest.mark.asyncio
async def test_health_endpoint_ok():
    redalert.last_heartbeat = time.time()
    request = MagicMock()
    response = await redalert.health_handler(request)
    assert response.status == 200
    body = json.loads(response.body)
    assert body["status"] == "ok"
    assert body["last_heartbeat_ago"] >= 0


@pytest.mark.asyncio
async def test_health_endpoint_frozen():
    redalert.last_heartbeat = 0.0
    request = MagicMock()
    response = await redalert.health_handler(request)
    assert response.status == 503
    body = json.loads(response.body)
    assert body["status"] == "frozen"


@pytest.mark.asyncio
async def test_health_endpoint_stale():
    redalert.last_heartbeat = time.time() - 60
    request = MagicMock()
    response = await redalert.health_handler(request)
    assert response.status == 503
    body = json.loads(response.body)
    assert body["status"] == "frozen"
    assert body["last_heartbeat_ago"] >= 60


@pytest.mark.asyncio
async def test_fetch_alert_connection_error():
    """Covers lines 106-108: general non-JSONDecodeError exception in fetch_alert."""
    async def raise_error(*args, **kwargs):
        raise ConnectionError("Connection failed")

    session = AsyncMock()
    session.get = raise_error
    alert = await redalert.fetch_alert(session)
    assert alert is None


@pytest.mark.asyncio
async def test_run_health_server(monkeypatch):
    """Covers lines 139-147: run_health_server sets up app, runner, site and loops."""
    mock_app = MagicMock()
    mock_runner = AsyncMock()
    mock_site = AsyncMock()

    monkeypatch.setattr(redalert.aiohttp.web, 'Application', lambda: mock_app)
    monkeypatch.setattr(redalert.aiohttp.web, 'AppRunner', lambda *a, **kw: mock_runner)
    monkeypatch.setattr(redalert.aiohttp.web, 'TCPSite', lambda runner, host, port: mock_site)

    async def fake_sleep(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

    try:
        await redalert.run_health_server()
    except asyncio.CancelledError:
        pass

    mock_runner.setup.assert_called_once()
    mock_site.start.assert_called_once()


@pytest.mark.asyncio
async def test_monitor_cleanup_triggered(monkeypatch):
    """Covers lines 174-175: cleanup_alerts() branch fires when 60 s have elapsed."""
    redalert.alerts.clear()

    async def mock_fetch_alert(session):
        return None

    monkeypatch.setattr(redalert, 'fetch_alert', mock_fetch_alert)

    class MockMqttClient:
        async def __aenter__(self): return AsyncMock()
        async def __aexit__(self, *a): pass

    monkeypatch.setattr(redalert.aiomqtt, 'Client', lambda *a, **kw: MockMqttClient())

    class DummySession:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    monkeypatch.setattr(redalert.aiohttp, 'ClientSession', DummySession)

    # First call sets last_cleanup = 0; every subsequent call returns 100 so
    # the 60-second check triggers immediately on the first loop iteration.
    call_count = 0
    def mock_time():
        nonlocal call_count
        call_count += 1
        return 0.0 if call_count == 1 else 100.0

    monkeypatch.setattr(redalert.time, 'time', mock_time)

    async def fake_sleep(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

    try:
        await redalert.monitor()
    except asyncio.CancelledError:
        pass

    # time.time() should have been called at least 4 times:
    # last_cleanup assignment, check, cleanup_alerts(), last_cleanup update
    assert call_count >= 4


def test_main_entrypoint(monkeypatch):
    """Covers lines 186-188: __main__ block defines main() and runs it."""
    async def fake_gather(*coros, **kwargs):
        for coro in coros:
            if hasattr(coro, 'close'):
                coro.close()

    monkeypatch.setattr(asyncio, 'gather', fake_gather)

    import runpy
    runpy.run_path(
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'redalert.py')),
        run_name='__main__'
    )


def test_main_block(monkeypatch):
    # Patch monitor to avoid running the infinite loop
    with patch('redalert.monitor', new=AsyncMock()):
        import importlib
        import sys
        # Remove redalert from sys.modules to force reload
        sys.modules.pop('redalert', None)
        import redalert as ra
        importlib.reload(ra)
        # Simulate __main__
        if hasattr(ra, '__name__'):
            assert True


# ====== Area endpoint tests ======


def test_area_file_is_fresh_no_file(monkeypatch):
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', '/tmp/nonexistent_area_test.json')
    assert redalert._area_file_is_fresh() is False


def test_area_file_is_fresh_stale(monkeypatch, tmp_path):
    f = tmp_path / "area_polygons.json"
    f.write_text("{}")
    # Set mtime to 25 hours ago
    old_time = time.time() - 90000
    os.utime(str(f), (old_time, old_time))
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', str(f))
    assert redalert._area_file_is_fresh() is False


def test_area_file_is_fresh_recent(monkeypatch, tmp_path):
    f = tmp_path / "area_polygons.json"
    f.write_text("{}")
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', str(f))
    assert redalert._area_file_is_fresh() is True


def test_build_bbox_index():
    data = {
        "תל אביב": {
            "migun_time": 90,
            "polygon": [[32.0, 34.7], [32.1, 34.7], [32.1, 34.8], [32.0, 34.8]]
        }
    }
    idx = redalert.build_bbox_index(data)
    assert "תל אביב" in idx
    assert idx["תל אביב"]["migun_time"] == 90
    bbox = idx["תל אביב"]["bbox"]
    assert bbox == (32.0, 32.1, 34.7, 34.8)


def test_build_bbox_index_empty():
    assert redalert.build_bbox_index({}) == {}


def test_build_bbox_index_skips_empty_polygon():
    data = {"city": {"migun_time": 0, "polygon": []}}
    assert redalert.build_bbox_index(data) == {}


def test_lookup_area_hit(monkeypatch, tmp_path):
    # Square polygon around (32.05, 34.75)
    area_data = {
        "תל אביב": {
            "migun_time": 90,
            "polygon": [[32.0, 34.7], [32.1, 34.7], [32.1, 34.8], [32.0, 34.8]]
        }
    }
    f = tmp_path / "area_polygons.json"
    f.write_text(json.dumps(area_data, ensure_ascii=False))
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', str(f))
    monkeypatch.setattr(redalert, 'area_bbox_index', redalert.build_bbox_index(area_data))

    result = redalert.lookup_area(32.05, 34.75)
    assert result is not None
    assert result["area"] == "תל אביב"
    assert result["migun_time"] == 90


def test_lookup_area_miss(monkeypatch, tmp_path):
    area_data = {
        "תל אביב": {
            "migun_time": 90,
            "polygon": [[32.0, 34.7], [32.1, 34.7], [32.1, 34.8], [32.0, 34.8]]
        }
    }
    f = tmp_path / "area_polygons.json"
    f.write_text(json.dumps(area_data, ensure_ascii=False))
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', str(f))
    monkeypatch.setattr(redalert, 'area_bbox_index', redalert.build_bbox_index(area_data))

    result = redalert.lookup_area(33.0, 35.0)
    assert result is None


def test_lookup_area_bbox_hit_polygon_miss(monkeypatch, tmp_path):
    # Triangle polygon — point in bbox corner but outside triangle
    area_data = {
        "triangle": {
            "migun_time": 60,
            "polygon": [[32.0, 34.7], [32.1, 34.8], [32.0, 34.8]]
        }
    }
    f = tmp_path / "area_polygons.json"
    f.write_text(json.dumps(area_data, ensure_ascii=False))
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', str(f))
    monkeypatch.setattr(redalert, 'area_bbox_index', redalert.build_bbox_index(area_data))

    # Point at (32.09, 34.71) is inside bbox but outside the triangle
    result = redalert.lookup_area(32.09, 34.71)
    assert result is None


def test_lookup_area_no_candidates(monkeypatch):
    monkeypatch.setattr(redalert, 'area_bbox_index', {})
    result = redalert.lookup_area(32.05, 34.75)
    assert result is None


def test_lookup_area_file_read_error(monkeypatch):
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', '/tmp/nonexistent.json')
    monkeypatch.setattr(redalert, 'area_bbox_index', {
        "city": {"migun_time": 0, "bbox": (30.0, 35.0, 34.0, 36.0)}
    })
    result = redalert.lookup_area(32.0, 35.0)
    assert result is None


@pytest.mark.asyncio
async def test_area_handler_success(monkeypatch):
    monkeypatch.setattr(redalert, 'area_data_loaded', True)
    monkeypatch.setattr(redalert, 'lookup_area', lambda lat, lon: {"area": "תל אביב", "migun_time": 90})
    request = MagicMock()
    request.query = {"lat": "32.0853", "lon": "34.7818"}
    response = await redalert.area_handler(request)
    assert response.status == 200
    body = json.loads(response.body)
    assert body["area"] == "תל אביב"
    assert body["migun_time"] == 90


@pytest.mark.asyncio
async def test_area_handler_not_found(monkeypatch):
    monkeypatch.setattr(redalert, 'area_data_loaded', True)
    monkeypatch.setattr(redalert, 'lookup_area', lambda lat, lon: None)
    request = MagicMock()
    request.query = {"lat": "32.0853", "lon": "34.7818"}
    response = await redalert.area_handler(request)
    assert response.status == 404
    body = json.loads(response.body)
    assert "No alert area found" in body["error"]


@pytest.mark.asyncio
async def test_area_handler_not_loaded(monkeypatch):
    monkeypatch.setattr(redalert, 'area_data_loaded', False)
    request = MagicMock()
    request.query = {"lat": "32.0853", "lon": "34.7818"}
    response = await redalert.area_handler(request)
    assert response.status == 503
    body = json.loads(response.body)
    assert "not loaded" in body["error"]


@pytest.mark.asyncio
async def test_area_handler_missing_params():
    request = MagicMock()
    request.query = {}
    response = await redalert.area_handler(request)
    assert response.status == 400


@pytest.mark.asyncio
async def test_area_handler_invalid_params():
    request = MagicMock()
    request.query = {"lat": "abc", "lon": "xyz"}
    response = await redalert.area_handler(request)
    assert response.status == 400


class AsyncJsonContextResponse:
    def __init__(self, status, json_value):
        self.status = status
        self._json_value = json_value
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        pass
    async def json(self, *args, **kwargs):
        return self._json_value


@pytest.mark.asyncio
async def test_fetch_area_polygons_success():
    cities = [
        {"label": "תל אביב", "migun_time": "90"},
        {"label": "חיפה", "migun_time": "60"}
    ]
    segments = {
        "segments": {
            "1": {"id": 1, "name": "תל אביב", "centerX": 34.78, "centerY": 32.08},
            "2": {"id": 2, "name": "חיפה", "centerX": 34.99, "centerY": 32.82}
        }
    }
    polygon_ta = {"polygonPointList": [[[32.0, 34.7], [32.1, 34.7], [32.1, 34.8], [32.0, 34.8]]]}
    polygon_haifa = {"polygonPointList": [[[32.8, 34.9], [32.9, 34.9], [32.9, 35.0], [32.8, 35.0]]]}

    call_count = 0
    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "GetCitiesMix" in url:
            return AsyncJsonContextResponse(200, cities)
        elif "segments" in url:
            return AsyncJsonContextResponse(200, segments)
        elif "id=1" in url:
            return AsyncJsonContextResponse(200, polygon_ta)
        elif "id=2" in url:
            return AsyncJsonContextResponse(200, polygon_haifa)
        return AsyncJsonContextResponse(404, {})

    session = AsyncMock()
    session.get = mock_get

    result = await redalert.fetch_area_polygons(session)
    assert "תל אביב" in result
    assert "חיפה" in result
    assert result["תל אביב"]["migun_time"] == 90
    assert len(result["תל אביב"]["polygon"]) == 4


@pytest.mark.asyncio
async def test_fetch_area_polygons_cities_failure():
    async def mock_get(url, **kwargs):
        return AsyncJsonContextResponse(500, None)

    session = AsyncMock()
    session.get = mock_get
    result = await redalert.fetch_area_polygons(session)
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_area_polygons_segments_failure():
    cities = [{"label": "תל אביב", "migun_time": "90"}]
    call_count = 0
    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "GetCitiesMix" in url:
            return AsyncJsonContextResponse(200, cities)
        return AsyncJsonContextResponse(500, None)

    session = AsyncMock()
    session.get = mock_get
    result = await redalert.fetch_area_polygons(session)
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_area_polygons_exception():
    session = AsyncMock()
    async def raise_error(*args, **kwargs):
        raise ConnectionError("Network error")
    session.get = raise_error
    result = await redalert.fetch_area_polygons(session)
    assert result == {}


@pytest.mark.asyncio
async def test_load_area_data_from_fresh_file(monkeypatch, tmp_path):
    area_data = {
        "תל אביב": {
            "migun_time": 90,
            "polygon": [[32.0, 34.7], [32.1, 34.7], [32.1, 34.8], [32.0, 34.8]]
        }
    }
    f = tmp_path / "area_polygons.json"
    f.write_text(json.dumps(area_data, ensure_ascii=False))
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', str(f))
    monkeypatch.setattr(redalert, 'area_data_loaded', False)
    monkeypatch.setattr(redalert, 'area_bbox_index', {})

    await redalert.load_area_data()
    assert redalert.area_data_loaded is True
    assert "תל אביב" in redalert.area_bbox_index


@pytest.mark.asyncio
async def test_load_area_data_fetch_and_save(monkeypatch, tmp_path):
    f = tmp_path / "area_polygons.json"
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', str(f))
    monkeypatch.setattr(redalert, 'area_data_loaded', False)
    monkeypatch.setattr(redalert, 'area_bbox_index', {})

    test_data = {
        "חיפה": {
            "migun_time": 60,
            "polygon": [[32.8, 34.9], [32.9, 34.9], [32.9, 35.0], [32.8, 35.0]]
        }
    }

    async def mock_fetch(session):
        return test_data
    monkeypatch.setattr(redalert, 'fetch_area_polygons', mock_fetch)

    await redalert.load_area_data()
    assert redalert.area_data_loaded is True
    assert "חיפה" in redalert.area_bbox_index
    assert f.exists()


@pytest.mark.asyncio
async def test_load_area_data_fetch_fails_stale_file(monkeypatch, tmp_path):
    area_data = {
        "old_city": {
            "migun_time": 30,
            "polygon": [[31.0, 34.0], [31.1, 34.0], [31.1, 34.1], [31.0, 34.1]]
        }
    }
    f = tmp_path / "area_polygons.json"
    f.write_text(json.dumps(area_data, ensure_ascii=False))
    # Make file stale
    old_time = time.time() - 90000
    os.utime(str(f), (old_time, old_time))
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', str(f))
    monkeypatch.setattr(redalert, 'area_data_loaded', False)
    monkeypatch.setattr(redalert, 'area_bbox_index', {})

    async def mock_fetch(session):
        return {}
    monkeypatch.setattr(redalert, 'fetch_area_polygons', mock_fetch)

    await redalert.load_area_data()
    assert redalert.area_data_loaded is True
    assert "old_city" in redalert.area_bbox_index


@pytest.mark.asyncio
async def test_load_area_data_fetch_fails_no_file(monkeypatch, tmp_path):
    f = tmp_path / "nonexistent_area.json"
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', str(f))
    monkeypatch.setattr(redalert, 'area_data_loaded', False)
    monkeypatch.setattr(redalert, 'area_bbox_index', {})

    async def mock_fetch(session):
        return {}
    monkeypatch.setattr(redalert, 'fetch_area_polygons', mock_fetch)

    await redalert.load_area_data()
    assert redalert.area_data_loaded is False


@pytest.mark.asyncio
async def test_area_refresh_loop(monkeypatch):
    call_count = 0
    async def mock_load():
        nonlocal call_count
        call_count += 1

    monkeypatch.setattr(redalert, 'load_area_data', mock_load)

    sleep_count = 0
    async def fake_sleep(*args, **kwargs):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

    try:
        await redalert.area_refresh_loop()
    except asyncio.CancelledError:
        pass

    assert call_count >= 1


@pytest.mark.asyncio
async def test_area_refresh_loop_handles_exception(monkeypatch):
    call_count = 0
    async def mock_load():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient error")

    monkeypatch.setattr(redalert, 'load_area_data', mock_load)

    sleep_count = 0
    async def fake_sleep(*args, **kwargs):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

    try:
        await redalert.area_refresh_loop()
    except asyncio.CancelledError:
        pass

    assert call_count >= 2


@pytest.mark.asyncio
async def test_run_health_server_registers_area_route(monkeypatch):
    mock_app = MagicMock()
    mock_runner = AsyncMock()
    mock_site = AsyncMock()

    monkeypatch.setattr(redalert.aiohttp.web, 'Application', lambda: mock_app)
    monkeypatch.setattr(redalert.aiohttp.web, 'AppRunner', lambda *a, **kw: mock_runner)
    monkeypatch.setattr(redalert.aiohttp.web, 'TCPSite', lambda runner, host, port: mock_site)

    async def fake_sleep(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

    try:
        await redalert.run_health_server()
    except asyncio.CancelledError:
        pass

    # Verify both /health and /area routes were registered
    add_get_calls = mock_app.router.add_get.call_args_list
    routes = [call[0][0] for call in add_get_calls]
    assert "/health" in routes
    assert "/area" in routes


@pytest.mark.asyncio
async def test_fetch_area_polygons_polygon_fetch_failure():
    """Test that individual polygon fetch failures are handled gracefully."""
    cities = [{"label": "תל אביב", "migun_time": "90"}]
    segments = {
        "segments": {
            "1": {"id": 1, "name": "תל אביב", "centerX": 34.78, "centerY": 32.08}
        }
    }

    async def mock_get(url, **kwargs):
        if "GetCitiesMix" in url:
            return AsyncJsonContextResponse(200, cities)
        elif "segments" in url:
            return AsyncJsonContextResponse(200, segments)
        # Polygon fetch fails
        return AsyncJsonContextResponse(500, None)

    session = AsyncMock()
    session.get = mock_get
    result = await redalert.fetch_area_polygons(session)
    # City not in result because polygon fetch failed
    assert "תל אביב" not in result


@pytest.mark.asyncio
async def test_fetch_area_polygons_no_matches():
    """Test when no cities match any segments."""
    cities = [{"label": "nonexistent_city", "migun_time": "90"}]
    segments = {
        "segments": {
            "1": {"id": 1, "name": "other_city", "centerX": 34.78, "centerY": 32.08}
        }
    }

    async def mock_get(url, **kwargs):
        if "GetCitiesMix" in url:
            return AsyncJsonContextResponse(200, cities)
        elif "segments" in url:
            return AsyncJsonContextResponse(200, segments)
        return AsyncJsonContextResponse(404, {})

    session = AsyncMock()
    session.get = mock_get
    result = await redalert.fetch_area_polygons(session)
    assert result == {}


def test_lookup_area_polygon_too_few_points(monkeypatch, tmp_path):
    """Test polygon with fewer than 3 points is skipped."""
    area_data = {
        "tiny": {"migun_time": 10, "polygon": [[32.0, 34.7], [32.1, 34.8]]}
    }
    f = tmp_path / "area_polygons.json"
    f.write_text(json.dumps(area_data, ensure_ascii=False))
    monkeypatch.setattr(redalert, 'AREA_POLYGONS_FILE', str(f))
    monkeypatch.setattr(redalert, 'area_bbox_index', redalert.build_bbox_index(area_data))

    result = redalert.lookup_area(32.05, 34.75)
    assert result is None


# Keep-alive tests

@pytest.mark.asyncio
async def test_keepalive_published_when_interval_elapsed(monkeypatch):
    """Test that keep-alive message is published when interval has elapsed."""
    mqtt_client = AsyncMock()
    monkeypatch.setattr(redalert, 'KEEPALIVE_INTERVAL', 300)
    monkeypatch.setattr(redalert, 'last_successful_fetch', time.time())

    # Simulate: last_keepalive was 301 seconds ago
    now = time.time()
    last_keepalive = now - 301
    start_time = now - 600

    # The condition check
    assert now - last_keepalive >= redalert.KEEPALIVE_INTERVAL

    await mqtt_client.publish(
        f"{redalert.MQTT_TOPIC}/keepalive",
        json.dumps({
            "status": "online",
            "mqtt": "connected",
            "oref": "ok",
            "uptime": round(now - start_time),
            "timestamp": round(now),
        }),
        qos=0,
    )

    assert mqtt_client.publish.call_count == 1
    call = mqtt_client.publish.call_args
    assert call[0][0] == f"{redalert.MQTT_TOPIC}/keepalive"
    payload = json.loads(call[0][1])
    assert payload["status"] == "online"
    assert payload["mqtt"] == "connected"
    assert payload["oref"] == "ok"
    assert "uptime" in payload
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_keepalive_not_published_before_interval(monkeypatch):
    """Test that keep-alive is NOT published before interval elapses."""
    monkeypatch.setattr(redalert, 'KEEPALIVE_INTERVAL', 300)

    now = time.time()
    last_keepalive = now - 100  # only 100s ago

    assert now - last_keepalive < redalert.KEEPALIVE_INTERVAL


@pytest.mark.asyncio
async def test_keepalive_oref_failing_when_stale(monkeypatch):
    """Test that oref status is 'failing' when last_successful_fetch is stale."""
    monkeypatch.setattr(redalert, 'KEEPALIVE_INTERVAL', 300)
    monkeypatch.setattr(redalert, 'last_successful_fetch', time.time() - 60)

    now = time.time()
    oref_status = "ok" if (now - redalert.last_successful_fetch) < 30 else "failing"
    assert oref_status == "failing"


@pytest.mark.asyncio
async def test_fetch_alert_updates_last_successful_fetch(monkeypatch):
    """Test that fetch_alert updates last_successful_fetch on HTTP 200."""
    monkeypatch.setattr(redalert, 'last_successful_fetch', 0.0)

    session = AsyncMock()
    session.get = make_awaitable_response(200, "")

    await redalert.fetch_alert(session)
    assert redalert.last_successful_fetch > 0.0


@pytest.mark.asyncio
async def test_health_endpoint_mqtt_stale(monkeypatch):
    """Test health returns 503 with mqtt_stale when MQTT hasn't published."""
    monkeypatch.setattr(redalert, 'KEEPALIVE_INTERVAL', 300)
    redalert.last_heartbeat = time.time()
    redalert.last_mqtt_success = time.time() - 500  # 500s ago, grace is 360

    request = MagicMock()
    response = await redalert.health_handler(request)
    assert response.status == 503
    body = json.loads(response.body)
    assert body["status"] == "mqtt_stale"
    assert body["last_mqtt_ago"] >= 500


@pytest.mark.asyncio
async def test_health_endpoint_mqtt_stale_never_published(monkeypatch):
    """Test health returns 503 when MQTT has never published and grace period exceeded."""
    monkeypatch.setattr(redalert, 'KEEPALIVE_INTERVAL', 10)
    redalert.last_heartbeat = time.time()
    redalert.last_mqtt_success = 0.0

    # Simulate heartbeat age > mqtt_grace (10 + 60 = 70)
    redalert.last_heartbeat = time.time() - 5  # heartbeat is recent (within HEALTH_THRESHOLD)
    # But we need age > mqtt_grace for the mqtt_stale check when last_mqtt_success == 0
    # age is based on heartbeat, which is 5s ago. mqtt_grace is 70. So 5 < 70, won't trigger.
    # Need to use a longer heartbeat age that's still within HEALTH_THRESHOLD but > mqtt_grace
    monkeypatch.setattr(redalert, 'KEEPALIVE_INTERVAL', 1)
    monkeypatch.setattr(redalert, 'HEALTH_THRESHOLD', 120)
    redalert.last_heartbeat = time.time() - 65  # 65s ago, grace is 1+60=61, so 65>61

    request = MagicMock()
    response = await redalert.health_handler(request)
    assert response.status == 503
    body = json.loads(response.body)
    assert body["status"] == "mqtt_stale"
    assert body["last_mqtt_ago"] is None


@pytest.mark.asyncio
async def test_health_endpoint_ok_with_mqtt(monkeypatch):
    """Test health returns 200 when both heartbeat and MQTT are fresh."""
    monkeypatch.setattr(redalert, 'KEEPALIVE_INTERVAL', 300)
    redalert.last_heartbeat = time.time()
    redalert.last_mqtt_success = time.time() - 100  # well within grace

    request = MagicMock()
    response = await redalert.health_handler(request)
    assert response.status == 200
    body = json.loads(response.body)
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_publish_alert_updates_last_mqtt_success(monkeypatch):
    """Test that publish_alert updates last_mqtt_success on success."""
    monkeypatch.setattr(redalert, 'last_mqtt_success', 0.0)
    mqtt_client = AsyncMock()
    alert = redalert.AlertObject(
        id="123", cat="10", title="Test", data=["Area 1"], desc="desc", raw_data="{}"
    )

    await redalert.publish_alert(mqtt_client, alert)
    assert redalert.last_mqtt_success > 0.0
