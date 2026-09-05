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
