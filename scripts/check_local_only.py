"""Check that the Tascam BD-MP4K integration only talks to its own player.

Runs with the Python standard library only (no installs), on Python 3.10+.
It reads the integration's manifest and source code and fails when it finds
anything that could send data elsewhere:

1. Manifest: the IoT class is local, no cloud, webhook or MQTT dependencies, and
   no Python requirements.
2. No listeners: nothing opens a server, webhook, HTTP view, UDP endpoint or a
   socket that binds, listens or receives.
3. One way out: the player's TCP control protocol, opened with asyncio streams in
   protocol.py only, never to a literal address. No HTTP, TLS or other network
   library is used at all.
4. One exception, Wake-on-LAN: a single UDP broadcast in wol.py, to the limited
   broadcast address only (see the settings below).
5. No hard-coded internet addresses: no URLs with a host, public host names or
   IP addresses in the code; every address comes from the configuration.

What it does not cover: Home Assistant itself. The runtime side (every
connection goes to the configured host and port) is checked by the tests.

Usage: python3 scripts/check_local_only.py [path/to/custom_components/<domain>]
"""

from __future__ import annotations

import ast
import ipaddress
import json
from pathlib import Path
import re
import sys

# ---------------------------------------------------------------------------
# Settings for this integration
# ---------------------------------------------------------------------------
# The player is controlled over its plain-text TCP protocol (port 9030 by default,
# set in the config flow) through asyncio streams. This is the only file that may
# open a connection, and it may only connect to the configured host.
CONNECTION_FILES = {"protocol.py"}
# Names of client objects whose connect calls are allowed elsewhere: none. The
# config flow and the entities go through TascamClient, which lives in protocol.py.
CLIENT_NAMES: set[str] = set()
# Files that may create Home Assistant HTTP client sessions: none, there is no HTTP.
SESSION_FILES: set[str] = set()
# Python requirements that are allowed: none, the protocol client is built in.
ALLOWED_REQUIREMENTS: set[str] = set()
# Modules this protocol never needs, so they are forbidden here as well.
UNUSED_MODULES = {"aiohttp", "ssl", "homeassistant.helpers.aiohttp_client"}

# Exception: Wake-on-LAN. The control protocol cannot switch the player on from
# standby, so wol.py sends the standard magic packet (six 0xFF bytes and the
# player's MAC address, nothing else) as one UDP datagram to port 9 of the limited
# broadcast address 255.255.255.255. Routers never forward that address, so the
# packet stays on the local network segment; it is not sent to the player's own IP
# address, because a player in standby has none that answers. This file is the only
# one allowed to use the socket module, and only for that: a UDP socket, sendto()
# to the broadcast address, and no binding, listening, receiving or connecting.
WOL_FILE = "wol.py"
WOL_BROADCAST = "255.255.255.255"
# Literal addresses that are allowed, per file.
ALLOWED_ADDRESSES: dict[str, set[str]] = {WOL_FILE: {WOL_BROADCAST}}

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
FORBIDDEN_DEPENDENCIES = {"cloud", "mqtt", "webhook"}
# Manifest keys that make Home Assistant talk to another service for this integration.
FORBIDDEN_MANIFEST_KEYS = {"mqtt"}
# Modules that talk to the network on their own, or serve.
FORBIDDEN_MODULES = {
    "aiohttp.web",
    "ftplib",
    "http.client",
    "http.server",
    "httpx",
    "paho",
    "requests",
    "smtplib",
    "socket",
    "socketserver",
    "telnetlib",
    "urllib.request",
    "websockets",
    "xmlrpc",
    "homeassistant.components.cloud",
    "homeassistant.components.http",
    "homeassistant.components.mqtt",
    "homeassistant.components.webhook",
    "homeassistant.helpers.httpx_client",
    *UNUSED_MODULES,
}
# Calls that listen for incoming connections.
LISTEN_CALLS = {
    "create_datagram_endpoint",
    "create_server",
    "create_unix_server",
    "register_view",
    "start_server",
    "start_unix_server",
}
# Raw socket calls that bind, listen, receive or connect. Wake-on-LAN only needs
# sendto(), so none of these is allowed anywhere.
RAW_SOCKET_CALLS = {
    "accept",
    "bind",
    "connect",
    "connect_ex",
    "listen",
    "recv",
    "recv_into",
    "recvfrom",
    "recvfrom_into",
    "recvmsg",
    "send",
    "sendall",
    "sendfile",
    "sendmsg",
}
# Calls that open outgoing connections.
CONNECT_CALLS = {"create_connection", "open_connection", "open_unix_connection", "ws_connect"}
SESSION_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "request"}
SESSION_FACTORIES = {"async_create_clientsession", "async_get_clientsession"}

_URL = re.compile(r"\b(?:https?|wss?|ftp|mqtts?|tcp|udp)://([^\s/'\"{}]+)", re.IGNORECASE)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_TLDS = "com|net|org|io|dev|app|cloud|ai|co|eu|nl|de|be|uk|fr|info|biz|me|tv|us"
_HOSTNAME = re.compile(rf"(?:[a-z0-9-]+\.)+(?:{_TLDS})", re.IGNORECASE)
# Example and local addresses never leave the network.
_HARMLESS_NETWORKS = [
    ipaddress.ip_network(net)
    for net in ("0.0.0.0/8", "127.0.0.0/8", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
]


def _harmless_ip(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return True  # Not an address (a version number, for instance).
    return any(address in network for network in _HARMLESS_NETWORKS)


def _call_name(node: ast.Call) -> tuple[str, str]:
    """Return (attribute or function name, name of the object it is called on)."""
    func = node.func
    if isinstance(func, ast.Attribute):
        owner = func.value
        if isinstance(owner, ast.Attribute):
            return func.attr, owner.attr
        if isinstance(owner, ast.Name):
            return func.attr, owner.id
        return func.attr, ""
    if isinstance(func, ast.Name):
        return func.id, ""
    return "", ""


def _literal_host(node: ast.Call) -> bool:
    """Return True when a connect call gets its host as a literal instead of a variable."""
    host = node.args[0] if node.args else None
    for keyword in node.keywords:
        if keyword.arg == "host":
            host = keyword.value
    return isinstance(host, ast.Constant)


def _broadcast_target(node: ast.Call) -> bool:
    """Return True when sendto() targets (WOL_BROADCAST, port)."""
    if len(node.args) != 2 or not isinstance(node.args[1], ast.Tuple):
        return False
    target = node.args[1].elts
    return (
        len(target) == 2
        and isinstance(target[0], ast.Constant)
        and target[0].value == WOL_BROADCAST
    )


def _is_udp_socket(node: ast.Call) -> bool:
    """Return True when socket.socket() is created with SOCK_DGRAM (UDP)."""
    return any(
        isinstance(arg, ast.Attribute) and arg.attr == "SOCK_DGRAM"
        for arg in [*node.args, *(k.value for k in node.keywords)]
    )


def check_manifest(integration: Path) -> list[str]:
    """Check the manifest for cloud use and extra requirements."""
    manifest = json.loads((integration / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    iot_class = str(manifest.get("iot_class", ""))
    if not iot_class.startswith("local_"):
        problems.append(f"manifest.json: iot_class is {iot_class!r}, not local_*")
    dependencies = set(manifest.get("dependencies", [])) | set(
        manifest.get("after_dependencies", [])
    )
    for dependency in sorted(dependencies & FORBIDDEN_DEPENDENCIES):
        problems.append(f"manifest.json: depends on {dependency!r}")
    for key in sorted(FORBIDDEN_MANIFEST_KEYS & set(manifest)):
        problems.append(f"manifest.json: uses {key!r}")
    for requirement in manifest.get("requirements", []):
        name = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].lower()
        if name not in {r.lower() for r in ALLOWED_REQUIREMENTS}:
            problems.append(f"manifest.json: requirement {requirement!r} is not allowed")
    return problems


def _check_import(node: ast.Import | ast.ImportFrom, path: Path, where: str) -> list[str]:
    names = (
        [alias.name for alias in node.names]
        if isinstance(node, ast.Import)
        else [node.module or ""]
        + [f"{node.module}.{alias.name}" for alias in node.names if node.module]
    )
    problems = []
    for name in names:
        if name == "socket" and path.name == WOL_FILE:
            continue  # The Wake-on-LAN exception, see the settings.
        if any(name == m or name.startswith(f"{m}.") for m in FORBIDDEN_MODULES):
            problems.append(f"{where}: imports {name}")
    return problems


def _check_call(node: ast.Call, path: Path, where: str) -> list[str]:
    name, owner = _call_name(node)
    if name in LISTEN_CALLS:
        return [f"{where}: {name}() listens for connections"]
    if name in RAW_SOCKET_CALLS:
        return [f"{where}: {owner}.{name}() binds, listens, receives or connects a socket"]
    if name in CONNECT_CALLS:
        if path.name not in CONNECTION_FILES and owner not in CLIENT_NAMES:
            return [f"{where}: {name}() outside {sorted(CONNECTION_FILES)}"]
        if _literal_host(node):
            return [f"{where}: {name}() to a literal address instead of the configured host"]
    if name == "sendto":
        if path.name != WOL_FILE:
            return [f"{where}: sendto() outside {WOL_FILE}"]
        if not _broadcast_target(node):
            return [f"{where}: sendto() to something other than ({WOL_BROADCAST!r}, port)"]
    if name == "socket" and owner == "socket" and not _is_udp_socket(node):
        return [f"{where}: socket.socket() that is not a UDP (SOCK_DGRAM) socket"]
    if name in SESSION_METHODS and "session" in owner.lower():
        return [f"{where}: {owner}.{name}(): this integration has no HTTP"]
    if name in SESSION_FACTORIES and path.name not in SESSION_FILES:
        return [f"{where}: {name}(): this integration has no HTTP"]
    return []


def _check_literal(text: str, path: Path, where: str) -> list[str]:
    if text in ALLOWED_ADDRESSES.get(path.name, set()):
        return []
    problems = [f"{where}: hard-coded address {m.group(0)!r}" for m in _URL.finditer(text)]
    problems += [
        f"{where}: hard-coded IP address {m.group(0)!r}"
        for m in _IPV4.finditer(text)
        if not _harmless_ip(m.group(0))
    ]
    if _HOSTNAME.fullmatch(text.strip()):
        problems.append(f"{where}: hard-coded host name {text!r}")
    return problems


def check_source(path: Path, relative: str) -> list[str]:
    """Check one Python file of the integration."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    problems = []
    for node in ast.walk(tree):
        where = f"{relative}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            problems += _check_import(node, path, where)
        elif isinstance(node, ast.Call):
            problems += _check_call(node, path, where)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            problems += _check_literal(node.value, path, where)
    return problems


def find_integration(argv: list[str]) -> Path:
    """Return the integration folder (argument, or the only one in custom_components)."""
    if len(argv) > 1:
        return Path(argv[1])
    root = Path(__file__).resolve().parents[1] / "custom_components"
    folders = [p for p in root.iterdir() if (p / "manifest.json").is_file()]
    if len(folders) != 1:
        raise SystemExit(f"Expected one integration in {root}, found {len(folders)}")
    return folders[0]


def main(argv: list[str]) -> int:
    """Run all checks and report."""
    integration = find_integration(argv)
    problems = check_manifest(integration)
    files = sorted(integration.rglob("*.py"))
    for path in files:
        problems += check_source(path, str(path.relative_to(integration.parent)))

    print(f"Local-only check of {integration.name}: {len(files)} Python files")
    if problems:
        for problem in problems:
            print(f"  FAIL {problem}")
        return 1
    print("  OK   manifest: local IoT class, no cloud, webhook or MQTT, no requirements")
    print("  OK   no listeners, webhooks, HTTP views or receiving sockets")
    print(f"  OK   TCP only from {', '.join(sorted(CONNECTION_FILES))}, to the configured host")
    print("  OK   no HTTP, TLS or other network libraries")
    print(f"  OK   only socket use: one Wake-on-LAN broadcast in {WOL_FILE}")
    print("  OK   no hard-coded internet addresses")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
