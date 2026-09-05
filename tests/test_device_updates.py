"""Exercise real device/entity code with a simulated Bluetooth transport."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.scent_assistant import device as device_module
from custom_components.scent_assistant.const import DeviceType
from custom_components.scent_assistant.device import ScentDiffuserDevice
from custom_components.scent_assistant.sensor import DiffuserWorkRemainSensor, DiffuserPauseRemainSensor
from custom_components.scent_assistant.switch import DiffuserPowerSwitch, DiffuserFanSwitch
from test_aroma_link import FULL_STATUS, frame
from test_aroma_link import SCHEDULE
from custom_components.scent_assistant.number import WorkDurationNumber, PauseDurationNumber


@pytest.fixture
def device(monkeypatch):
    monkeypatch.setattr(device_module, "time", SimpleNamespace(monotonic=lambda: 100.0))
    device = ScentDiffuserDevice(
        ble_address="00:00:00:00:00:01", device_type=DeviceType.AROMA_LINK,
        live_updates=True,
    )
    device._ble_client = SimpleNamespace(is_connected=True, stop_notify=AsyncMock(), disconnect=AsyncMock())
    device._ble_connected = True
    return device


def receive(device, value=FULL_STATUS):
    for offset in range(0, len(value), 20):
        device._on_ble_notification(1, bytearray(value[offset:offset+20]))


def test_device_reply_reaches_entities_without_click(device):
    power = DiffuserPowerSwitch(device, None)
    fan = DiffuserFanSwitch(device, SimpleNamespace(data={"connection_mode": "ble"}))
    pause = DiffuserPauseRemainSensor(device, None)
    work = DiffuserWorkRemainSensor(device, None)
    assert not pause.available
    receive(device)
    receive(device, frame(b"\x52\x03\x10"))
    assert power.is_on is True
    assert fan.is_on is True
    assert pause.available
    assert pause.native_value == 40
    assert work.native_value == 0


def test_countdown_ticks_and_resynchronizes_without_changing_phase(device, monkeypatch):
    receive(device)
    monkeypatch.setattr(device_module.time, "monotonic", lambda: 107.9)
    assert device.countdown_remaining("pause_remaining") == 33
    assert device.state.pause_remaining == 40  # Keep the actual device sample.
    receive(device)
    assert device.countdown_remaining("pause_remaining") == 40
    monkeypatch.setattr(device_module.time, "monotonic", lambda: 148.0)
    assert device.countdown_remaining("pause_remaining") == 0
    assert device.state.phase == "paused"
    monkeypatch.setattr(device_module.time, "monotonic", lambda: 154.0)
    assert device.countdown_remaining("pause_remaining") is None


def test_phase_change_waits_for_fresh_counter(device):
    receive(device)
    receive(device, frame(bytes.fromhex("5309010032003c0000173b01")))
    assert device.countdown_remaining("work_remaining") is None


def test_disconnect_discards_fragment_and_marks_live_entities_unavailable(device):
    receive(device)
    device._on_ble_notification(1, bytearray(FULL_STATUS[:20]))
    device._on_ble_disconnect(device._ble_client)
    assert not device.available
    assert device.countdown_remaining("pause_remaining") is None
    assert not device._protocol._notification_buffer
    assert device._ble_has_synced_time is False
    device._ble_connected = True
    receive(device)
    assert device.available


def test_normal_idle_disconnect_preserves_on_demand_values():
    device = ScentDiffuserDevice(ble_address="00:00:00:00:00:01", device_type=DeviceType.AROMA_LINK)
    receive(device)
    assert device.available
    assert device.countdown_remaining("pause_remaining") == 40


async def test_refresh_reads_fan_and_full_status(device, monkeypatch):
    device._ble_connect = AsyncMock(return_value=True)
    monkeypatch.setattr(device_module.asyncio, "sleep", AsyncMock())
    writes = []

    async def send(command):
        writes.append(command[4:-3])
        if command[4:-3] == b"\x52\x03":
            receive(device, frame(b"\x52\x03\x00"))
        elif command[4:-3] == b"\x52\x0a":
            receive(device)
        return True

    device._ble_send = send
    await device.refresh_state(include_metadata=False)
    assert writes == [b"\x52\x03", b"\x52\x0a"]
    assert device.state.fan is False
    assert device.state.power is True
    assert device.state.pause_remaining == 40


async def test_commands_cannot_interleave_refresh(device):
    entered, release = asyncio.Event(), asyncio.Event()

    async def refresh(**kwargs):
        entered.set()
        await release.wait()

    device._refresh_state_locked = refresh
    device._ble_execute_locked = AsyncMock(return_value=True)
    refresh_task = asyncio.create_task(device.refresh_state())
    await entered.wait()
    command_task = asyncio.create_task(device._ble_execute(b"command"))
    assert not device._ble_execute_locked.called
    release.set()
    await refresh_task
    assert await command_task
    device._ble_execute_locked.assert_awaited_once_with(b"command")


async def test_live_cadence_and_retry_backoff(device, monkeypatch):
    receive(device)
    device.refresh_state = AsyncMock()
    await device.async_live_update()
    device.refresh_state.assert_awaited_once_with(include_metadata=True)
    await device.async_live_update()
    assert device.refresh_state.await_count == 1
    monkeypatch.setattr(device_module.time, "monotonic", lambda: 105.0)
    await device.async_live_update()
    device.refresh_state.assert_awaited_with(include_metadata=False)
    device._on_ble_disconnect(device._ble_client)
    monkeypatch.setattr(device_module.time, "monotonic", lambda: 110.0)
    await device.async_live_update()
    assert device._next_live_refresh == 140


async def test_slow_poll_does_not_stack_another_poll(device):
    receive(device)
    entered, release = asyncio.Event(), asyncio.Event()

    async def refresh(**kwargs):
        entered.set()
        await release.wait()

    device.refresh_state = AsyncMock(side_effect=refresh)
    task = asyncio.create_task(device.async_live_update())
    await entered.wait()
    await device.async_live_update()
    device.refresh_state.assert_awaited_once()
    release.set()
    await task


async def test_live_never_schedules_idle_disconnect_and_shutdown_releases_notify(device):
    device._schedule_disconnect()
    assert device._ble_disconnect_task is None
    device._ble_notify_subscribed = True
    client = device._ble_client
    await device.async_shutdown()
    client.stop_notify.assert_awaited_once()
    client.disconnect.assert_awaited_once()
    assert not await device._ble_connect()
    device.refresh_state = AsyncMock()
    await device.async_live_update()
    device.refresh_state.assert_not_awaited()


async def test_sync_time_works_on_existing_connection(device):
    device._ble_connect = AsyncMock(return_value=True)
    device._ble_send = AsyncMock(return_value=True)
    assert await device.sync_time()
    assert device._ble_send.call_args.args[0][4:6] == b"\x57\x17"


async def test_transport_connect_and_reconnect(monkeypatch):
    clients = []

    async def connect(*args, **kwargs):
        client = Mock(is_connected=True)
        client.start_notify = AsyncMock()
        client.stop_notify = AsyncMock()
        client.disconnect = AsyncMock()
        clients.append(client)
        return client

    monkeypatch.setattr(device_module, "establish_connection", connect)
    device = ScentDiffuserDevice(ble_address="00:00:00:00:00:01", device_type=DeviceType.AROMA_LINK, live_updates=True)
    device._ble_send = AsyncMock(return_value=True)
    assert await device._ble_connect()
    clients[0].start_notify.assert_awaited_once()
    assert device._ble_disconnect_task is None
    assert device._ble_send.await_count == 1  # Time sync.
    device._on_ble_disconnect(clients[0])
    clients[0].is_connected = False
    assert await device._ble_connect()
    assert len(clients) == 2
    assert device._ble_send.await_count == 2
    await device.async_shutdown()


def test_duration_entities_do_not_publish_fabricated_defaults_on_reload(device):
    work, pause = WorkDurationNumber(device, None), PauseDurationNumber(device, None)
    receive(device)
    assert work.native_value is None and pause.native_value is None
    assert not work.available and not pause.available
    receive(device, SCHEDULE)
    assert work.available and pause.available
    assert (work.native_value, pause.native_value) == (50, 60)
