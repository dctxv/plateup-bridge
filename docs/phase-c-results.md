
## Phase C control frequency -- 2026-07-28 12:52

| Hz | arrived | median s | median err | max overshoot |
|---:|---:|---:|---:|---:|
| 10 | 8/8 | 0.46 | 0.161 | 0.000 |
| 12 | 8/8 | 0.42 | 0.148 | 0.000 |
| 15 | 8/8 | 0.45 | 0.174 | 0.000 |
| 20 | 8/8 | 0.44 | 0.165 | 0.000 |

Choose the lowest rate meeting the motor gate: >=98% arrival, <=2% overshoot failures. Lower rates mean fewer policy evaluations per game second.

NOTE: this uses a proportional controller, not a learned policy. It measures what the control channel can support, not final motor quality. Re-measure after the motor policy exists.

## Phase C safety -- 2026-07-28 12:58

### Command expiry
- watchdog stop: **0.33s** after last command
- drift after last command: **1.55** world units
- verdict: PASS

### Hard disconnect
- drift after hard client kill: **0.000** world units
- verdict: PASS

### Phase transitions
- frames observed: **7241**
- frames with input captured: **0**
- motion while captured: **0** (want 0)
- verdict: INCONCLUSIVE

## Phase C soak -- 2026-07-28 13:01

- commands sent: **727**
- observations received: **726**
- duration: **21s** (35 cmd/s)
- max round-trip gap: **76ms**
- stalls >1s: **0**
- errors: **0**
- verdict: PASS

## Phase C soak -- 2026-07-28 13:02

- commands sent: **2345**
- observations received: **2344**
- duration: **66s** (35 cmd/s)
- max round-trip gap: **59ms**
- stalls >1s: **0**
- errors: **0**
- verdict: PASS

## Phase C soak -- 2026-07-28 13:03

- commands sent: **392**
- observations received: **391**
- duration: **11s** (35 cmd/s)
- max round-trip gap: **73ms**
- stalls >1s: **0**
- errors: **0**
- verdict: PASS

## Phase C soak -- 2026-07-28 13:15

- commands sent: **23786**
- observations received: **23786**
- duration: **667s** (36 cmd/s)
- max round-trip gap: **191ms**
- stalls >1s: **0**
- errors: **1**
  - 23786: position frozen 600 frames
- verdict: FAIL

## Phase C safety -- 2026-07-28 13:58

### Command expiry
- watchdog stop: **0.03s** after last command
- drift after last command: **0.00** world units
- verdict: PASS

### Hard disconnect
- drift after hard client kill: **0.000** world units
- verdict: PASS

### Phase transitions
- frames observed: **486**
- frames with input captured: **0**
- motion while captured: **0** (want 0)
- verdict: INCONCLUSIVE

Phase C closed

Against the revised gate:

	
Per-axis movement	✅
Button edges	✅
Player routing	✅
Receipts / echo	✅ built
Expiry + release	✅ 0.33s, 1.55u
Hard disconnect	✅ 0.000u
Phase transitions	⚠️ inconclusive — pause uses Time.IsPaused, not capture
Throw/drop	✅ identified as non-existent
Frequency	✅ 10 Hz, channel not limiting
Soak	✅ 24k clean; re-run for the full 100k