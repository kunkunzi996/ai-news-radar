from __future__ import annotations

from scripts.radar.server import *  # noqa: F401,F403

"""Bilibili dedicated browser and CDP cookie helpers."""

def port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def find_available_port(start_port: int) -> int:
    for port in range(start_port, start_port + 50):
        if not port_is_open(port):
            return port
    raise RuntimeError(f"no available local port from {start_port}")


def cdp_json(port: int, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=3.0) as response:
        return json.loads(response.read().decode("utf-8"))


def cdp_ready(port: int) -> bool:
    try:
        return bool(cdp_json(port, "/json/version").get("Browser"))
    except Exception:
        return False


def find_chrome_executable() -> str | None:
    configured = str(os.environ.get("BILIBILI_CHROME_PATH") or os.environ.get("MEDIACRAWLER_CHROME_PATH") or "").strip()
    if configured and Path(configured).is_file():
        return configured
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def launch_bilibili_dedicated_browser(root_dir: Path, *, execute: bool = True) -> dict[str, Any]:
    profile_dir = (root_dir / BILIBILI_PROFILE_DIR).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = BILIBILI_CDP_PORT if cdp_ready(BILIBILI_CDP_PORT) else find_available_port(BILIBILI_CDP_PORT)
    chrome = find_chrome_executable()
    if not chrome:
        return {"ok": False, "error": "chrome_not_found"}
    command = [
        chrome,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--start-maximized",
        BILIBILI_LOGIN_URL,
    ]
    if not execute:
        return {
            "ok": True,
            "kind": "start_service",
            "action_id": "open_bilibili_login",
            "command": command,
            "profile_dir": str(profile_dir),
            "cdp_port": port,
            "executed": False,
        }
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags)
    return {
        "ok": True,
        "kind": "start_service",
        "action_id": "open_bilibili_login",
        "pid": process.pid,
        "profile_dir": str(profile_dir),
        "cdp_port": port,
        "next_action": "在这个专用窗口登录B站小号，然后回本页点同步cookie。",
        "executed": True,
    }


def active_bilibili_cdp_port() -> int | None:
    for port in range(BILIBILI_CDP_PORT, BILIBILI_CDP_PORT + 8):
        if cdp_ready(port):
            return port
    return None


def cdp_new_page(port: int, url: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(url, safe=":/?=&")
    for method in ("PUT", "GET"):
        request = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{encoded}", method=method, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=3.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            if method == "PUT":
                continue
            raise
    return {}


def read_websocket_frame(sock: socket.socket) -> bytes:
    header = sock.recv(2)
    if len(header) < 2:
        return b""
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", sock.recv(8))[0]
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def sync_bilibili_cookie(root_dir: Path, *, execute: bool = True) -> dict[str, Any]:
    port = active_bilibili_cdp_port()
    if not port:
        return {"ok": False, "error": "bilibili_login_window_not_running"}
    payload = cdp_new_page(port, BILIBILI_COOKIE_URL)
    websocket_url = str(payload.get("webSocketDebuggerUrl") or "")
    if not websocket_url:
        return {"ok": False, "error": "cdp_target_not_available"}
    import base64

    parsed = urllib.parse.urlparse(websocket_url)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {parsed.path} HTTP/1.1\r\n"
        f"Host: {parsed.netloc}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode("ascii")
    with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or port), timeout=5) as sock:
        sock.sendall(request)
        response = sock.recv(4096)
        if b" 101 " not in response:
            return {"ok": False, "error": "websocket_upgrade_failed"}
        message = json.dumps({"id": 1, "method": "Network.getAllCookies"}).encode("utf-8")
        header = bytearray([0x81])
        length = len(message)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(message))
        sock.sendall(bytes(header) + masked)
        data = None
        for _attempt in range(20):
            raw = read_websocket_frame(sock)
            if not raw:
                continue
            candidate = json.loads(raw.decode("utf-8"))
            if candidate.get("id") == 1:
                data = candidate
                break
        if data is None:
            return {"ok": False, "error": "websocket_cookie_response_missing"}
    cookies = [
        cookie for cookie in data.get("result", {}).get("cookies", [])
        if "bilibili.com" in str(cookie.get("domain") or "")
    ]
    if not cookies:
        return {"ok": False, "error": "bilibili_cookie_not_found"}
    cookie_text = "; ".join(f"{cookie.get('name')}={cookie.get('value')}" for cookie in cookies if cookie.get("name") and cookie.get("value"))
    if "SESSDATA=" not in cookie_text:
        return {"ok": False, "error": "bilibili_login_cookie_missing_sessdata"}
    cookie_file = (root_dir / BILIBILI_DEFAULT_COOKIE_FILE).resolve()
    if execute:
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        cookie_file.write_text(cookie_text + "\n", encoding="utf-8")
    return {
        "ok": True,
        "kind": "start_service",
        "action_id": "sync_bilibili_cookie",
        "cookie_file": str(cookie_file),
        "cookie_count": len(cookies),
        "has_sessdata": True,
        "executed": execute,
    }



