# Upstream review — 2026-09-06

Reviewed stable v1.2.2 (`e377ed4`) and main/v1.2.3-beta.1 (`ac928a7`).

| Behavior | v1.2.2 | v1.2.3-beta.1 | Remaining work in this fork |
| --- | --- | --- | --- |
| Fragmented U5 full status | Ignored | Parsed | Retain split-header/coalesced-frame coverage and disconnect reset |
| Power and phase from full status | Ignored | Parsed | Use upstream correction |
| `53 09` countdowns | Stored as configuration | Correct remaining fields | Use upstream correction |
| Fan `52 03` read | Neither requested nor parsed | Neither requested nor parsed | Request and parse real setting |
| Autonomous reads | Startup only | Every 300 seconds | Optional persistent connection with frequent reads and per-second countdown estimates |
| Configured BLE durations | No readback | `52 06` from vendor code, hardware not yet verified upstream | Retain register and add captured U5 `52 15` fallback; no fabricated number defaults |
| Discovery missing at startup | Address passed to BLEDevice-only connector | Same | Wait and retry with a discovered BLEDevice |

Replayed the sanitized U5 full-status capture through both actual release
parsers using 20-byte notifications: v1.2.2 returned no fields; the beta returned
power, paused phase, and 50/40-second remaining values. Both ignored the real
`52 03 10` fan reply. This confirms overlap and the remaining fan gap without
changing Home Assistant to an untested upstream build.

The merged branch contains all upstream commits, including the v1.2.2 GATT
write-mode, cloud schedule, device detection, multi-pump and momentary-duration
changes. Normal mode retains upstream polling. Live mode suppresses that second
timer and respects Home Assistant's polling preference.

Release notes:
- https://github.com/mr-sparks/scent-assistant/releases/tag/v1.2.2
- https://github.com/mr-sparks/scent-assistant/releases/tag/v1.2.3-beta.1

The merged build still needs hardware validation. The previously installed
1.2.1.post2 build recovered after startup and read the U5's stored 50/60-second
configuration and fan setting without a control click.
