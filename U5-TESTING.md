# Aromadd U5 state-update test build

This fork's `fix/u5-state-v1.2.1` branch is based on upstream **v1.2.1**,
with the packet/state fixes and optional live mode. Its integration version is
**1.2.1.post2**. It does not include the unrelated changes on upstream's
1.2.2 beta branch. This is a hardware-validation build, not an upstream release.

## Verified locally

- A U5 full-status reply delivered in 20-byte Bluetooth fragments was ignored
  by the original parser. Replaying a sanitized capture now populates power,
  phase, schedule window, and both remaining-time values.
- The vendor app reads fan state using `52 03`. The fix sends that query and
  accepts its `52 03` reply as well as `53 03` unsolicited changes.
- Regression tests run with Home Assistant 2026.9.0 and Python 3.14.3.
  They exercise real integration classes with a simulated Bluetooth transport.
- Existing entity unique IDs and device/config-entry identifiers are retained.
- Live U5 testing exposed a separate startup bug: configured durations were
  never read back, so number entities could publish defaults that automations
  would then save. The `52 15` table is now parsed, including disabled slots;
  unavailable duration data is never replaced with fabricated defaults.

## Installation and rollback

1. Create a Home Assistant backup and retain a copy of the currently installed
   `config/custom_components/scent_assistant` directory.
2. Close the Aroma-Link/Aromadd app on every phone/tablet.
3. Copy the test build's `custom_components/scent_assistant` directory over the
   existing directory in Home Assistant's configuration directory. Do not
   delete or recreate the integration entry.
4. Restart Home Assistant so Python loads the changed files. A config-entry
   reload alone does not reliably reload modified Python modules.
5. Confirm diagnostics report version `1.2.1.post2`. Check power, fan, status,
   and remaining-time entities before clicking any controls.
6. In the integration's **Configure** options, enable **Enable live updates**.
   The entry reloads automatically. Leave **Enable polling for updates** on.
7. Verify the existing HVAC/schedule automation still behaves normally. Once
   live mode is confirmed, the extra periodic time-sync workaround is normally
   unnecessary; leave it as-is until deciding to remove that workaround.

To roll back, disable live mode, restore the saved integration directory (or
redownload upstream v1.2.1 in HACS), and restart Home Assistant. Keep the
integration entry so entity IDs and automations remain intact. HACS may replace
this test build on a later upstream download/update.

## Hardware validation checklist

- Check diagnostics immediately after startup: power and fan should be known
  without toggling them, and the full-status packet should populate counters.
- Observe at least two complete work/pause cycles in live mode. The active
  countdown should tick once per second and correct itself on full-status
  reports; the inactive countdown displays zero.
- Confirm repeated `52 0A` requests receive `52 0A` or `53 0A` replies. Some
  firmware only sends full status after time sync. If this unit does not answer
  the repeated read, retain the notification/command diagnostics for further
  analysis; a continuously synchronized countdown is not yet verified.
- Confirm the fan read returns its real setting, including after an existing
  automation changes it. Test controls only when appropriate for the attached
  HVAC system, preserving the original settings.
- Reload the integration and check it recovers automatically. If a Bluetooth
  outage occurs, live entities should become unavailable and recover after the
  connection and status replies return. Automatic failed retries are spaced by
  at least 30 seconds.
- Disable live mode, wait for the normal idle disconnect, and verify the
  vendor app can connect again.

Countdown values between reports are estimates, exposed through the
`estimated_between_updates` attribute. The integration never invents the next
phase after a countdown expires. Raw full-status frames can contain a device
MAC address; redact identifying bytes before sharing diagnostics publicly.
