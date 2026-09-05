"""Check HA setup/options lifecycle without starting a Bluetooth adapter."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components import scent_assistant as integration
from custom_components.scent_assistant.config_flow import ScentDiffuserConfigFlow, ScentDiffuserOptionsFlow
from custom_components.scent_assistant.const import DOMAIN


@pytest.mark.parametrize("live,disabled,mode,kind,expected", [
    (True, False, "ble", "aroma_link", True),
    (False, False, "ble", "aroma_link", False),
    (True, True, "ble", "aroma_link", False),
    (True, False, "cloud", "aroma_link", False),
    (True, False, "ble", "scentiment", False),
])
async def test_setup_registers_live_timer_only_when_requested(monkeypatch, live, disabled, mode, kind, expected):
    device = Mock()
    device.async_setup = AsyncMock()
    device.async_shutdown = AsyncMock()
    device.async_live_update = AsyncMock()
    factory = Mock(return_value=device)
    monkeypatch.setattr(integration, "ScentDiffuserDevice", factory)
    timer = Mock(return_value=Mock())
    monkeypatch.setattr(integration, "async_track_time_interval", timer)
    entry = SimpleNamespace(
        entry_id="test", data={"connection_mode": mode, "device_type": kind},
        options={"live_updates": live}, pref_disable_polling=disabled,
        async_on_unload=Mock(),
    )
    hass = SimpleNamespace(data={}, services=Mock(), config_entries=SimpleNamespace(
        async_forward_entry_setups=AsyncMock(), async_unload_platforms=AsyncMock(return_value=True),
    ))
    assert await integration.async_setup_entry(hass, entry)
    assert timer.called is expected
    if expected:
        assert timer.call_args.args[2].total_seconds() == 1
        entry.async_on_unload.assert_called_once_with(timer.return_value)
    assert await integration.async_unload_entry(hass, entry)
    device.async_shutdown.assert_awaited_once()
    assert "test" not in hass.data[DOMAIN]


@pytest.mark.parametrize("mode,kind,expected", [
    ("ble", "aroma_link", True), ("cloud", "aroma_link", False), ("ble", "scentiment", False),
])
def test_options_support_is_limited_to_aroma_link_ble(mode, kind, expected):
    entry = SimpleNamespace(data={"connection_mode": mode, "device_type": kind})
    assert ScentDiffuserConfigFlow.async_supports_options_flow(entry) is expected


async def test_options_default_off_and_preserve_existing_options():
    entry = SimpleNamespace(options={"other_option": 123})
    flow = ScentDiffuserOptionsFlow()
    flow.handler = "test"
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_known_entry=lambda _: entry))
    result = await flow.async_step_init()
    assert result["data_schema"]({}) == {"live_updates": False}
    result = await flow.async_step_init({"live_updates": True})
    assert result["data"] == {"other_option": 123, "live_updates": True}
