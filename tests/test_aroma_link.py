"""Regression coverage for U5 notifications captured through an HA BLE proxy."""
import pytest

from custom_components.scent_assistant.protocol_ble import AromaLinkBleProtocol


def frame(payload: bytes) -> bytes:
    """Wrap a payload independently of the production packet builder."""
    checksum = 0
    for byte in payload:
        checksum ^= byte
    return b"\xa5\xaa\xac" + bytes([checksum]) + payload + b"\xc5\xcc\xca"


# Real U5 full-status layout; identifying MAC bytes zeroed before committing.
FULL_STATUS = frame(bytes.fromhex(
    "530a07ea09050c000306100102003200280000173b01"
    "0000000000000000000001000000000000010100"
))


@pytest.mark.parametrize("split", range(1, len(FULL_STATUS)))
def test_split_status_is_atomic(split):
    protocol = AromaLinkBleProtocol()
    assert protocol.parse_notification(FULL_STATUS[:split]) == {}
    result = protocol.parse_notification(FULL_STATUS[split:])
    assert result["work_remaining"] == 50
    assert result["pause_remaining"] == 40
    assert result["power"] is True
    assert result["phase"] == "paused"
    assert (result["start_hour"], result["end_minute"]) == (0, 59)
    assert "battery" not in result


def test_actual_proxy_chunk_sizes():
    protocol = AromaLinkBleProtocol()
    assert protocol.parse_notification(FULL_STATUS[:20]) == {}
    assert protocol.parse_notification(FULL_STATUS[20:40]) == {}
    assert protocol.parse_notification(FULL_STATUS[40:])["pause_remaining"] == 40


def test_false_trailer_at_notification_boundary_keeps_pending_frame():
    packet = frame(bytes.fromhex("520a07ea09050c000306100102003200280000173b01c5ccca0102"))
    split = packet.index(b"\xc5\xcc\xca") + 3
    protocol = AromaLinkBleProtocol()
    assert protocol.parse_notification(packet[:split]) == {}
    assert protocol.parse_notification(packet[split:])["pause_remaining"] == 40


def test_upstream_frequency_register_reads_configuration_separately():
    packet = frame(bytes.fromhex("5206000032003c11") + bytes.fromhex("000a007810") * 4)
    protocol = AromaLinkBleProtocol()
    assert protocol.parse_notification(packet[:20]) == {}
    assert protocol.parse_notification(packet[20:]) == {
        "work_seconds": 50, "pause_seconds": 60, "schedule_enabled": True,
    }


@pytest.mark.parametrize("cmd", [0x52, 0x53])
@pytest.mark.parametrize("value,expected", [(0x10, True), (0, False)])
def test_fan_read_response_and_push(cmd, value, expected):
    assert AromaLinkBleProtocol().parse_notification(frame(bytes([cmd, 3, value]))) == {"fan": expected}


def test_bad_checksum_does_not_update_state():
    corrupt = bytearray(FULL_STATUS)
    corrupt[3] ^= 1
    assert AromaLinkBleProtocol().parse_notification(bytes(corrupt)) == {}


def test_truncated_cycle_does_not_raise():
    assert AromaLinkBleProtocol().parse_notification(frame(bytes.fromhex("5309010032003c000017"))) == {}


def test_multiple_frames_and_recovery():
    protocol = AromaLinkBleProtocol()
    # A new header replaces a lost/incomplete previous reply.
    assert protocol.parse_notification(FULL_STATUS[:20]) == {}
    result = protocol.parse_notification(FULL_STATUS + frame(b"\x52\x03\x10"))
    assert result["power"] is True
    assert result["fan"] is True


def test_query_builder_matches_vendor_fan_read():
    assert AromaLinkBleProtocol().build_fan_query() == frame(b"\x52\x03")


# Captured U5 table: seven days, five slots/day, slot 1 disabled, 50/60 s.
SCHEDULE = bytes.fromhex("a5aaac7552150000173b100032003c0000000010000a00780000000010000a00780000000010000a00780000000010000a00780000173b100032003c0000000010000a00780000000010000a00780000000010000a00780000000010000a00780000173b100032003c0000000010000a00780000000010000a00780000000010000a00780000000010000a00780000173b100032003c0000000010000a00780000000010000a00780000000010000a00780000000010000a00780000173b100032003c0000000010000a00780000000010000a00780000000010000a00780000000010000a00780000173b100032003c0000000010000a00780000000010000a00780000000010000a00780000000010000a00780000173b100032003c0000000010000a00780000000010000a00780000000010000a00780000000010000a0078c5ccca")


def test_real_schedule_reply_restores_disabled_program_durations():
    protocol = AromaLinkBleProtocol()
    result = {}
    for i in range(0, len(SCHEDULE), 20):
        result.update(protocol.parse_notification(SCHEDULE[i:i + 20]))
    assert result["work_seconds"] == 50
    assert result["pause_seconds"] == 60
    assert result["schedule_enabled"] is False
    assert result["end_minute"] == 59
    # Countdown data must not replace configured work/pause values.
    result = protocol.parse_notification(FULL_STATUS)
    assert result["work_seconds"] == 50
    assert result["pause_seconds"] == 60
    assert result["pause_remaining"] == 40


def test_schedule_tracks_device_weekday_and_ignores_empty_slots():
    protocol = AromaLinkBleProtocol()
    payload = bytearray(SCHEDULE[4:-3])
    # Saturday's first slot differs from the rest of the week.
    payload[2 + 5 * 45 + 5:2 + 5 * 45 + 9] = bytes.fromhex("001e005a")
    protocol.parse_notification(frame(bytes(payload)))
    result = protocol.parse_notification(FULL_STATUS)  # Saturday in the capture.
    assert (result["work_seconds"], result["pause_seconds"]) == (30, 90)


def test_schedule_cache_invalidated_after_write_or_disconnect():
    protocol = AromaLinkBleProtocol()
    protocol.parse_notification(SCHEDULE)
    protocol.invalidate_schedule()
    assert "work_seconds" not in protocol.parse_notification(FULL_STATUS)
    protocol.parse_notification(SCHEDULE)
    protocol.reset_notifications()
    assert "work_seconds" not in protocol.parse_notification(FULL_STATUS)


def test_truncated_schedule_is_not_accepted():
    assert AromaLinkBleProtocol().parse_notification(frame(SCHEDULE[4:-4])) == {}
