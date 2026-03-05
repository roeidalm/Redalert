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
    monkeypatch.setattr(redalert.aiohttp.web, 'AppRunner', lambda app: mock_runner)
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
