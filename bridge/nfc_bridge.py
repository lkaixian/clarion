#!/usr/bin/env python3
"""
CLARION / MediBridge -- Phase E: NFC local bridge.

A tiny helper that runs on the hospital reception PC. It talks to a USB
NFC/RFID card reader over a serial (COM) port and exposes the most recent
card tap to the web console over localhost HTTP.

  GET  /status      -> {"connected", "com_port", "device_name", "last_scan_at"}
  GET  /last-scan   -> {"nfc_uid", "scanned_at"}
  POST /debug/scan  -> {"nfc_uid": "..."}  (off unless a debug_token is set)

Design notes / guarantees:
  * NO patient data ever touches this program. It only ever emits a card
    UID string that the reader hands us.
  * Only the Python stdlib + pyserial are used. No web framework.
  * The serial read loop runs on a background thread; the HTTP server owns
    the main thread. A disconnected reader never crashes the process --
    the bridge just reports connected:false and keeps re-scanning ports.

Security (the UID is effectively a bearer credential for the backend's
unauthenticated /emergency/nfc/scan, so this endpoint is not "harmless"):
  * Bound to 127.0.0.1 only.
  * CORS is a strict allowlist (allowed_origins, default the Vite dev
    origins) -- NOT a wildcard and NOT an "any localhost" reflect, so a
    random website open in the reception browser cannot read /last-scan.
  * The Host header must be localhost/127.0.0.1 -- defeats DNS-rebinding.
  * /debug/scan is disabled unless `debug_token` is configured, and then
    requires that token (a browser page can't know it) on top of the
    localhost-IP check. Request bodies are size-capped.

Run:  python bridge/nfc_bridge.py
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import serial  # type: ignore
    from serial.tools import list_ports  # type: ignore
except ImportError:  # pragma: no cover - guidance only
    sys.stderr.write(
        "ERROR: pyserial is not installed. Run:\n"
        "    pip install -r bridge/requirements.txt\n"
    )
    raise SystemExit(1)


HTTP_PORT = 8770
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(HERE, "config.json")

# The web console's dev + typical preview origins. Override/extend via
# config.json "allowed_origins". No wildcard, no substring matching.
DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]
MAX_BODY_BYTES = 4096


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
    print(f"[{stamp}] {msg}", flush=True)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_uid(raw: str) -> str:
    """Trim, drop STX/ETX framing and inner spaces, upper-case."""
    uid = raw.strip().upper()
    for junk in (" ", "\t", "\x02", "\x03", "\r", "\n"):
        uid = uid.replace(junk, "")
    return uid


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
class Config:
    """
    Resolution order (highest priority first):
      1. CLI flags
      2. Environment variables (NFC_BRIDGE_*)
      3. bridge/config.json
      4. built-in defaults
    """

    def __init__(self) -> None:
        self.port: str | None = None          # explicit COM port, e.g. "COM3"
        self.vid: int | None = None           # USB vendor id (int or "0x1234")
        self.pid: int | None = None           # USB product id
        self.description_contains: str | None = None  # substring of port description
        self.baudrate: int = 9600
        self.reconnect_seconds: float = 3.0
        self.http_port: int = HTTP_PORT
        self.allowed_origins: list[str] = list(DEFAULT_ALLOWED_ORIGINS)
        self.debug_token: str | None = None  # /debug/scan is OFF unless this is set

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _as_int(value) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, int):
            return value
        return int(str(value), 0)  # accepts "0x1234" and "4660"

    def _apply_dict(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        if data.get("port"):
            self.port = str(data["port"]).strip()
        if data.get("vid") not in (None, ""):
            self.vid = self._as_int(data["vid"])
        if data.get("pid") not in (None, ""):
            self.pid = self._as_int(data["pid"])
        for key in ("description_contains", "description", "desc"):
            if data.get(key):
                self.description_contains = str(data[key]).strip()
        if data.get("baudrate"):
            self.baudrate = int(data["baudrate"])
        if data.get("reconnect_seconds"):
            self.reconnect_seconds = float(data["reconnect_seconds"])
        if data.get("http_port"):
            self.http_port = int(data["http_port"])
        origins = data.get("allowed_origins")
        if isinstance(origins, list) and origins:
            self.allowed_origins = [str(o).strip().rstrip("/") for o in origins if str(o).strip()]
        elif isinstance(origins, str) and origins.strip():
            self.allowed_origins = [o.strip().rstrip("/") for o in origins.split(",") if o.strip()]
        if data.get("debug_token"):
            self.debug_token = str(data["debug_token"])

    # -- loaders ---------------------------------------------------------
    def load_file(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self._apply_dict(json.load(fh))
            log(f"Loaded config from {path}")
        except (OSError, ValueError) as exc:
            log(f"WARNING: could not read config {path}: {exc}")

    def load_env(self) -> None:
        env = os.environ
        self._apply_dict(
            {
                "port": env.get("NFC_BRIDGE_PORT"),
                "vid": env.get("NFC_BRIDGE_VID"),
                "pid": env.get("NFC_BRIDGE_PID"),
                "description_contains": env.get("NFC_BRIDGE_DESC"),
                "baudrate": env.get("NFC_BRIDGE_BAUD"),
                "reconnect_seconds": env.get("NFC_BRIDGE_RECONNECT"),
                "http_port": env.get("NFC_BRIDGE_HTTP_PORT"),
                "allowed_origins": env.get("NFC_BRIDGE_ALLOWED_ORIGINS"),
                "debug_token": env.get("NFC_BRIDGE_DEBUG_TOKEN"),
            }
        )

    def apply_args(self, args: argparse.Namespace) -> None:
        self._apply_dict(
            {
                "port": args.port,
                "vid": args.vid,
                "pid": args.pid,
                "description_contains": args.desc,
                "baudrate": args.baud,
                "http_port": args.http_port,
                "allowed_origins": args.allowed_origins,
                "debug_token": args.debug_token,
            }
        )

    def summary(self) -> str:
        bits = []
        if self.port:
            bits.append(f"port={self.port}")
        if self.vid is not None:
            bits.append(f"vid=0x{self.vid:04x}")
        if self.pid is not None:
            bits.append(f"pid=0x{self.pid:04x}")
        if self.description_contains:
            bits.append(f'desc~"{self.description_contains}"')
        if not bits:
            bits.append("auto-detect (first available serial port)")
        return ", ".join(bits) + f", baud={self.baudrate}"


# --------------------------------------------------------------------------
# Shared state between the reader thread and the HTTP handlers
# --------------------------------------------------------------------------
class BridgeState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.connected = False
        self.com_port: str | None = None
        self.device_name: str | None = None
        self.nfc_uid: str | None = None
        self.scanned_at: str | None = None
        self.detail: str = "starting up"

    def set_connected(self, com_port: str, device_name: str | None) -> None:
        with self._lock:
            self.connected = True
            self.com_port = com_port
            self.device_name = device_name
            self.detail = f"connected to {com_port}"

    def set_disconnected(self, detail: str) -> None:
        with self._lock:
            self.connected = False
            self.com_port = None
            self.device_name = None
            self.detail = detail

    def record_scan(self, uid: str) -> None:
        with self._lock:
            self.nfc_uid = uid
            self.scanned_at = utcnow_iso()

    def status_payload(self) -> dict:
        with self._lock:
            return {
                "connected": self.connected,
                "com_port": self.com_port,
                "device_name": self.device_name,
                "last_scan_at": self.scanned_at,
                "detail": self.detail,
            }

    def last_scan_payload(self) -> dict:
        with self._lock:
            return {"nfc_uid": self.nfc_uid, "scanned_at": self.scanned_at}


# --------------------------------------------------------------------------
# Serial reader thread
# --------------------------------------------------------------------------
class ReaderThread(threading.Thread):
    def __init__(self, config: Config, state: BridgeState, stop_event: threading.Event) -> None:
        super().__init__(name="nfc-reader", daemon=True)
        self.config = config
        self.state = state
        self.stop_event = stop_event

    # -- port selection -------------------------------------------------
    def _pick_port(self):
        """Return a ListPortInfo matching the config, or None."""
        ports = list(list_ports.comports())
        cfg = self.config

        if cfg.port:
            for p in ports:
                if p.device.upper() == cfg.port.upper():
                    return p
            return None  # explicitly requested port not present yet

        def matches(p) -> bool:
            if cfg.vid is not None and p.vid != cfg.vid:
                return False
            if cfg.pid is not None and p.pid != cfg.pid:
                return False
            if cfg.description_contains:
                haystack = f"{p.description} {p.manufacturer or ''} {p.product or ''}".lower()
                if cfg.description_contains.lower() not in haystack:
                    return False
            return True

        candidates = [p for p in ports if matches(p)]

        # With no explicit filter we still auto-detect, but never grab an
        # obvious non-reader device -- Bluetooth virtual ports on Windows
        # otherwise cause a ~15s "semaphore timeout" every reconnect cycle.
        if not (cfg.vid is not None or cfg.pid is not None or cfg.description_contains):
            candidates = [
                p for p in candidates
                if "bluetooth" not in f"{p.description or ''} {p.manufacturer or ''}".lower()
            ]

        return candidates[0] if candidates else None

    # -- main loop ----------------------------------------------------
    def run(self) -> None:
        cfg = self.config
        announced_waiting = False

        while not self.stop_event.is_set():
            info = self._pick_port()
            if info is None:
                if not announced_waiting:
                    want = cfg.port or "any matching reader"
                    self.state.set_disconnected(f"no reader found (waiting for {want})")
                    log(f"No reader detected. Retrying every {cfg.reconnect_seconds:g}s...")
                    announced_waiting = True
                self.stop_event.wait(cfg.reconnect_seconds)
                continue

            announced_waiting = False
            try:
                self._read_from(info)
            except serial.SerialException as exc:
                self.state.set_disconnected(f"reader error: {exc}")
                log(f"Serial error on {info.device}: {exc}")
            except OSError as exc:
                self.state.set_disconnected(f"reader error: {exc}")
                log(f"OS error on {info.device}: {exc}")

            if not self.stop_event.is_set():
                log(f"Lost {info.device}. Re-scanning in {cfg.reconnect_seconds:g}s...")
                self.stop_event.wait(cfg.reconnect_seconds)

        log("Reader thread stopped.")

    def _read_from(self, info) -> None:
        cfg = self.config
        device_name = info.description or info.product or info.device
        log(f"Opening {info.device} ({device_name}) at {cfg.baudrate} baud...")

        with serial.Serial(info.device, cfg.baudrate, timeout=1) as ser:
            self.state.set_connected(info.device, device_name)
            log(f"Connected. Waiting for card taps on {info.device}.")

            while not self.stop_event.is_set():
                raw = ser.readline()
                if not raw:
                    continue  # just a read timeout, loop again
                try:
                    line = raw.decode("utf-8", errors="replace")
                except Exception:  # pragma: no cover - defensive
                    continue
                uid = normalize_uid(line)
                if not uid:
                    continue
                self.state.record_scan(uid)
                log(f"Card tap: {uid}")


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------
def make_handler(state: BridgeState, config: Config):
    allowed_origins = set(config.allowed_origins)
    allowed_hosts = {
        f"127.0.0.1:{config.http_port}",
        f"localhost:{config.http_port}",
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "ClarionNfcBridge/1.0"

        # Quieter default logging; we do our own.
        def log_message(self, fmt, *args):  # noqa: D401
            return

        # -- host allowlist (anti DNS-rebinding) --------------------
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").strip().lower()
            return host in allowed_hosts

        # -- CORS: strict allowlist, no wildcard, no reflect -------
        def _cors(self) -> None:
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if origin and origin in allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            # An origin not on the list simply gets no ACAO header -> the
            # browser blocks the response. We still answer the request so a
            # same-origin / curl caller works.
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Debug-Token")
            self.send_header("Access-Control-Max-Age", "600")

        def _send_json(self, payload: dict, code: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _reject_bad_host(self) -> bool:
            if self._host_ok():
                return False
            self._send_json({"error": "bad host"}, code=403)
            return True

        # -- verbs -------------------------------------------------
        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            if self._reject_bad_host():
                return
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path == "/status":
                self._send_json(state.status_payload())
            elif path == "/last-scan":
                self._send_json(state.last_scan_payload())
            elif path == "/":
                self._send_json(
                    {
                        "service": "clarion-nfc-bridge",
                        "endpoints": ["/status", "/last-scan"],
                    }
                )
            else:
                self._send_json({"error": "not found"}, code=404)

        def do_POST(self) -> None:
            if self._reject_bad_host():
                return
            path = self.path.split("?", 1)[0]
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            if path.rstrip("/") != "/debug/scan":
                self._send_json({"error": "not found"}, code=404)
                return

            # Disabled entirely unless a debug token is configured.
            if not config.debug_token:
                self._send_json({"error": "not found"}, code=404)
                return

            # Local machine only...
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self._send_json({"error": "forbidden"}, code=403)
                return

            # ...AND a matching token (a browser page can't know this).
            supplied = self.headers.get("X-Debug-Token")
            if not supplied:
                for part in query.split("&"):
                    if part.startswith("token="):
                        supplied = part[len("token="):]
                        break
            if not supplied or not hmac.compare_digest(supplied, config.debug_token):
                self._send_json({"error": "forbidden"}, code=403)
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_BODY_BYTES:
                    raise ValueError("body too large")
                data = json.loads(self.rfile.read(length) or b"{}")
                uid = normalize_uid(str(data["nfc_uid"]))
                if not uid:
                    raise ValueError("empty nfc_uid")
            except (ValueError, KeyError, TypeError) as exc:
                self._send_json({"error": f"bad request: {exc}"}, code=400)
                return
            state.record_scan(uid)
            log(f"DEBUG scan injected: {uid}")
            self._send_json({"ok": True, **state.last_scan_payload()})

    return Handler


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CLARION NFC local bridge (serial reader -> localhost HTTP)."
    )
    parser.add_argument("--port", help='explicit serial port, e.g. "COM3"')
    parser.add_argument("--vid", help="USB vendor id filter (e.g. 0x072F)")
    parser.add_argument("--pid", help="USB product id filter (e.g. 0x2200)")
    parser.add_argument("--desc", help="substring match on port description")
    parser.add_argument("--baud", type=int, help="baud rate (default 9600)")
    parser.add_argument("--http-port", type=int, help=f"HTTP port (default {HTTP_PORT})")
    parser.add_argument(
        "--allowed-origins",
        help="comma-separated CORS allowlist (default: the Vite dev origins)",
    )
    parser.add_argument(
        "--debug-token",
        help="enable POST /debug/scan and require this token (X-Debug-Token header or ?token=)",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="path to config.json (default: bridge/config.json)",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="print detected serial ports and exit",
    )
    return parser.parse_args(argv)


def print_ports() -> None:
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports detected.")
        return
    print(f"{len(ports)} serial port(s) detected:")
    for p in ports:
        vid = f"0x{p.vid:04x}" if p.vid is not None else "----"
        pid = f"0x{p.pid:04x}" if p.pid is not None else "----"
        print(f"  {p.device:<8} vid={vid} pid={pid}  {p.description}")


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.list_ports:
        print_ports()
        return 0

    config = Config()
    config.load_file(args.config)
    config.load_env()
    config.apply_args(args)

    log("CLARION NFC bridge starting.")
    log(f"Reader selection: {config.summary()}")
    log(f"CORS allowlist: {', '.join(config.allowed_origins)}")
    log(f"/debug/scan: {'enabled (token required)' if config.debug_token else 'disabled'}")
    log("Reminder: no patient data passes through this bridge -- card UID only.")

    state = BridgeState()
    stop_event = threading.Event()

    reader = ReaderThread(config, state, stop_event)
    reader.start()

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", config.http_port), make_handler(state, config))
    except OSError as exc:
        log(f"FATAL: cannot bind HTTP port {config.http_port}: {exc}")
        stop_event.set()
        return 1

    log(f"HTTP listening on http://localhost:{config.http_port}  (GET /status, GET /last-scan)")
    log("Open the web console's NFC tab now. Press Ctrl+C to stop.")

    def shutdown(signum, _frame):
        log(f"Signal {signum} received -- shutting down.")
        stop_event.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for signame in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, signame, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, shutdown)
        except (OSError, ValueError):  # pragma: no cover - not on main thread etc.
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - belt and braces
        stop_event.set()
    finally:
        httpd.server_close()
        stop_event.set()
        reader.join(timeout=3)
        log("Bye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
