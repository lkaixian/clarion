# CLARION / MediBridge — Phase E: NFC local bridge

A small helper program that runs on the **hospital reception PC**. It talks to a
USB NFC/RFID card reader over a serial (COM) port and exposes the **most recent
card tap** to the CLARION web console over `localhost` HTTP.

The web console (`web/src/pages/Reception.jsx`, the `useNfcBridge` hook and the
"NFC Card" identifier mode) already polls this bridge. This directory is *only*
the bridge program plus its docs.

## What it does / does not do

- It reads a **card UID string** from a serial reader and caches the latest one.
- It serves that UID to the browser on a fixed local port.
- **No patient data ever touches this program.** It only ever emits a card UID.
  Mapping a UID to a patient happens server-side in the CLARION backend.
- It never crashes on a missing/unplugged reader — it reports `connected: false`
  and keeps re-scanning the serial ports.

## HTTP API (fixed port `8770`)

| Method | Path          | Response |
| ------ | ------------- | -------- |
| GET    | `/status`     | `{ "connected": bool, "com_port": string\|null, "device_name": string\|null, "last_scan_at": ISO8601\|null }` (plus a human-readable `detail`) |
| GET    | `/last-scan`  | `{ "nfc_uid": string\|null, "scanned_at": ISO8601\|null }` |
| OPTIONS| any           | `204` with CORS headers (preflight) |
| POST   | `/debug/scan` | Testing aid. **Disabled** unless `debug_token` is configured; then requires that token + a localhost caller. Body `{ "nfc_uid": "04A1B2C3" }`. |

### Why this is locked down

The card UID this bridge emits is effectively a **bearer credential**: the
CLARION backend's `/emergency/nfc/scan` is unauthenticated and returns a
patient's emergency record for a valid UID. So the bridge must not let a
random web page read `/last-scan`:

- **Bound to `127.0.0.1` only** — never `0.0.0.0`. The web console must run on
  the same PC.
- **CORS is a strict allowlist** (`allowed_origins`, default the Vite dev/preview
  origins `http://localhost:5173` / `:4173`). Not a wildcard, not an "any
  localhost" reflect. An origin not on the list gets **no** `Access-Control-Allow-Origin`
  header, so the browser blocks the response.
- **`Host` header must be `localhost`/`127.0.0.1`** — defeats DNS-rebinding
  (a page resolving its own hostname to `127.0.0.1`).
- **`/debug/scan` is off by default.** Set `debug_token` (config/env/`--debug-token`)
  to enable it; callers then need that token via an `X-Debug-Token` header or
  `?token=` — which a browser page cannot know — plus be on the local machine.
- Request bodies are size-capped (4 KB).

If you serve the console from a non-default origin, add it to `allowed_origins`.

## Install

Requires Python 3.9+ (tested on 3.14) and one dependency, `pyserial`.

```powershell
cd "C:\Users\Larm Kai Xian\Desktop\dins 2026\medibridge_package"
python -m pip install -r bridge/requirements.txt
```

(Optional but tidy: create a venv first — `python -m venv bridge/.venv` then
`bridge\.venv\Scripts\Activate.ps1`.)

## Run

```powershell
python bridge/nfc_bridge.py
```

You should see:

```
[2026-08-27 09:00:00+0800] CLARION NFC bridge starting.
[2026-08-27 09:00:00+0800] Reader selection: auto-detect (first available serial port), baud=9600
[2026-08-27 09:00:00+0800] HTTP listening on http://localhost:8770
```

**Start the bridge BEFORE staff open the NFC tab** in the web console. The tab
only polls while it is selected; if the bridge is not running the tab shows the
reader as unreachable.

Stop with **Ctrl+C** — it shuts the HTTP server and reader thread down cleanly.

### See which ports exist

```powershell
python bridge/nfc_bridge.py --list-ports
```

```
2 serial port(s) detected:
  COM3     vid=0x072f pid=0x2200  USB-Serial CH340 (PICC reader)
  COM1     vid=---- pid=----      Communications Port
```

## Configure the reader port

By default the bridge auto-detects: it enumerates serial ports with
`serial.tools.list_ports` and opens the first plausible one (Bluetooth virtual
ports are skipped). To pin it down, use **any one** of:

### Option A — `bridge/config.json`

```powershell
copy bridge\config.example.json bridge\config.json
notepad bridge\config.json
```

Keys (all optional):

| Key                     | Meaning |
| ----------------------- | ------- |
| `port`                  | Explicit port, e.g. `"COM3"`. Wins over the filters below. |
| `vid` / `pid`           | USB vendor/product id filter. Hex (`"0x072F"`) or decimal. |
| `description_contains`  | Case-insensitive substring of the port description. |
| `baudrate`              | Default `9600`. Common alternatives: `115200`, `19200`. |
| `reconnect_seconds`     | Re-scan interval when no reader is present. Default `3`. |
| `http_port`             | Default `8770` — don't change unless you also set `VITE_NFC_BRIDGE_URL`. |
| `allowed_origins`       | CORS allowlist (array of exact `scheme://host:port`). Default: the Vite dev/preview origins. |
| `debug_token`           | Empty = `/debug/scan` disabled (default). Set a random string to enable it for testing. |

`config.json` is git-ignored (it is per-PC); `config.example.json` is committed.

### Option B — environment variables

`NFC_BRIDGE_PORT`, `NFC_BRIDGE_VID`, `NFC_BRIDGE_PID`, `NFC_BRIDGE_DESC`,
`NFC_BRIDGE_BAUD`, `NFC_BRIDGE_RECONNECT`, `NFC_BRIDGE_HTTP_PORT`,
`NFC_BRIDGE_ALLOWED_ORIGINS` (comma-separated), `NFC_BRIDGE_DEBUG_TOKEN`.

```powershell
$env:NFC_BRIDGE_PORT = "COM3"; python bridge/nfc_bridge.py
```

### Option C — command-line flags

```powershell
python bridge/nfc_bridge.py --port COM3 --baud 9600
python bridge/nfc_bridge.py --vid 0x072F --pid 0x2200
python bridge/nfc_bridge.py --desc "PICC"
```

Priority: **CLI flags > env vars > `config.json` > defaults.**

## Point the web console at the bridge

The web app reads `import.meta.env.VITE_NFC_BRIDGE_URL` and defaults to
`http://localhost:8770`. If the bridge runs on the default port on the same PC,
**nothing to do**.

To be explicit, or if the bridge runs elsewhere / on a non-default port, add to
`web/.env`:

```
VITE_NFC_BRIDGE_URL=http://localhost:8770
```

Then restart the Vite dev server (`npm run dev`) so the value is picked up.

## Reader / driver notes

Most cheap USB NFC readers fall into one of two camps:

1. **Keyboard-wedge (HID)** — types the UID as if it were a keyboard. These do
   **not** expose a COM port and this bridge cannot use them. Many such readers
   have a config card to switch them into "virtual COM / serial" mode — do that.
2. **CDC / USB-serial** — shows up as a COM port. This is what the bridge wants.
   - **CH340 / CH341** chip: install the WCH `CH341SER` driver. Port appears as
     `USB-Serial CH340 (COMx)`.
   - **CP210x** (Silicon Labs): install the SiLabs `CP210x` VCP driver.
   - **FTDI**: usually plug-and-play on Windows 11; otherwise the FTDI `VCP`
     driver.
   - **ACR122U / PN532 dev boards**: these are PC/SC or I2C/SPI devices, *not*
     line-oriented serial. Not supported by this bridge without a firmware/mode
     that emits UID lines over UART.

The bridge expects the reader to emit the **card UID as a line** terminated by
CR/LF (optionally wrapped in STX/ETX or containing spaces — those are stripped).
The UID is whitespace-trimmed and upper-cased before caching. If your reader uses
a different framing, adjust `_read_from()` in `nfc_bridge.py`.

Typical serial settings: `9600 8N1`. If you see garbage, try `--baud 115200`.

## Testing without hardware

Start the bridge (no reader attached is fine):

```powershell
python bridge/nfc_bridge.py
```

Check the endpoints (PowerShell has `curl` aliased to `Invoke-WebRequest`; use
`curl.exe` for the real thing):

```powershell
curl.exe -i http://localhost:8770/status
curl.exe -i http://localhost:8770/last-scan
curl.exe -i -X OPTIONS http://localhost:8770/status
```

- `/status` → `connected: false` with `detail` like `no reader found (waiting for any matching reader)`.
- `/last-scan` → `{"nfc_uid": null, "scanned_at": null}`.
- `OPTIONS` → `204` with `Access-Control-Allow-Origin` etc.

Simulate a card tap with the debug endpoint — first enable it with a token:

```powershell
python bridge/nfc_bridge.py --debug-token test123
# in another shell:
curl.exe -i -X POST "http://localhost:8770/debug/scan?token=test123" -H "Content-Type: application/json" -d "{\"nfc_uid\": \"04A1B2C3D4\"}"
curl.exe http://localhost:8770/last-scan
# -> {"nfc_uid": "04A1B2C3D4", "scanned_at": "2026-08-27T..."}
```

The web console's NFC tab will then auto-fill that UID into the check-in field.
Without `--debug-token`, `/debug/scan` returns `404` (disabled) — leave it that
way in normal use.

## Files

| File                  | Purpose |
| --------------------- | ------- |
| `nfc_bridge.py`       | The whole bridge — serial reader thread + stdlib HTTP server. |
| `requirements.txt`    | `pyserial`. |
| `config.example.json` | Template — copy to `config.json` and edit. |
| `config.json`         | Your per-PC config (git-ignored). |
| `.gitignore`          | Ignores `__pycache__/`, `config.json`, venvs. |
