"""The session server (decision D14, #90): hooks hand their payload to a process that already has the store open.

**Why it exists.** A hook that starts `amem` pays for:
- a fresh Python process and the engine's imports, about 60 ms;
- opening the store.

On real Claude Code sessions that put hook p50 at about 170 ms. The session
server keeps one store open for the whole session. A hook then costs a few
milliseconds of shell plus the work itself, including the durable write,
which still happens before the hook returns.

**Agent-neutral.** The server belongs to the engine, not to one adapter. It is
started by whatever long-lived process the agent has:
- `amem mcp` starts it beside the MCP server. That covers agents that run
  shell hooks and an MCP server (Claude Code, and the Stage 3.5 agents with
  hooks).
- `amem serve` runs it alone, until its stdin closes. That's for agents
  whose plugins run in-process (OpenCode, Pi): the plugin starts it once
  per session and keeps the connection open.

Any adapter falls back to running `amem hook` directly when no server answers.

**Protocol** (one hook per connection; TCP on 127.0.0.1, so a Windows client
reaches a server inside WSL through WSL's localhost forwarding):
1. The server says `AMEM1 <server-id>\\n`. The client checks it against the
   server file before sending anything, so a stale file never sends a
   payload to an unrelated program that reused the port.
2. The client sends `AMEM1 <token> <agent> <event> <bytes>\\n`, then the
   payload.
3. The server answers `OK\\n` and the hook's output, or `ERR <reason>\\n`. The
   client then falls back to the direct path, and the idempotency keys keep
   that from storing anything twice.

**The server file** `<store>/run/server` (mode 0600) holds
`<port> <server-id> <token> <pid>`. Only a process that can read it can use
the server, which is the same trust boundary as the store itself.

Hooks and MCP tool calls in one process are serialized by `LOCK`.
"""
from __future__ import annotations

import hmac
import os
import secrets
import socket
import socketserver
import sys
import threading
from pathlib import Path

PROTOCOL = "AMEM1"
LOCK = threading.RLock()      # one store user at a time in this process: hooks and MCP tool calls
MAX_PAYLOAD = 64 * 1024 * 1024
HEADER_LIMIT = 512
TAKEOVER_EVERY = 5.0          # seconds between checks for a server that went away
CLIENT_TIMEOUT = 60.0


def server_file(store_dir) -> Path:
    return Path(store_dir) / "run" / "server"


def read_server_file(store_dir) -> dict | None:
    try:
        port, sid, token, pid = server_file(store_dir).read_text().split()[:4]
        return {"port": int(port), "sid": sid, "token": token, "pid": int(pid)}
    except (OSError, ValueError):
        return None


def ping(store_dir, timeout: float = 1.0) -> bool:
    """True if the server named in the server file answers as itself."""
    info = read_server_file(store_dir)
    if info is None:
        return False
    try:
        with socket.create_connection(("127.0.0.1", info["port"]), timeout=timeout) as s:
            f = s.makefile("rb")
            if f.readline(HEADER_LIMIT).decode(errors="replace").strip() != f"{PROTOCOL} {info['sid']}":
                return False
            s.sendall(f"{PROTOCOL} {info['token']} - ping 0\n".encode())
            return f.readline(HEADER_LIMIT).strip() == b"OK"
    except OSError:
        return False


def forward(store_dir, agent: str, event: str, payload: bytes, timeout: float = CLIENT_TIMEOUT) -> str | None:
    """The Python client (for adapters and tests): the hook's output, or None to fall back to the direct path."""
    info = read_server_file(store_dir)
    if info is None:
        return None
    try:
        with socket.create_connection(("127.0.0.1", info["port"]), timeout=timeout) as s:
            f = s.makefile("rb")
            if f.readline(HEADER_LIMIT).decode(errors="replace").strip() != f"{PROTOCOL} {info['sid']}":
                return None
            s.sendall(f"{PROTOCOL} {info['token']} {agent} {event} {len(payload)}\n".encode() + payload)
            if f.readline(HEADER_LIMIT).strip() != b"OK":
                return None
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return None


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        srv: SessionServer = self.server.owner   # type: ignore[attr-defined]
        try:
            self.request.settimeout(CLIENT_TIMEOUT)
            self.wfile.write(f"{PROTOCOL} {srv.sid}\n".encode())
            self.wfile.flush()
            header = self.rfile.readline(HEADER_LIMIT).decode("ascii", errors="replace").split()
            if len(header) != 5 or header[0] != PROTOCOL or not hmac.compare_digest(header[1], srv.token):
                self.wfile.write(b"ERR unauthorized\n")
                return
            _, _, agent, event, size = header
            size = int(size)
            if not 0 <= size <= MAX_PAYLOAD:
                self.wfile.write(b"ERR too large\n")
                return
            if event == "ping":
                self.wfile.write(b"OK\n")
                return
            payload = self.rfile.read(size)
            if len(payload) != size:
                self.wfile.write(b"ERR short payload\n")
                return
            out = srv.run_hook(agent, event, payload)
            self.wfile.write(b"OK\n" + out.encode("utf-8"))
        except (OSError, ValueError) as err:
            try:
                self.wfile.write(f"ERR {type(err).__name__}\n".encode())
            except OSError:
                pass


class _TCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False


class SessionServer:
    """Serves hooks for one project's store, from inside a long-lived process.

    `start()` claims the server file unless another live server holds it. A
    background thread keeps checking, and takes over when that server goes
    away (for example, the session that started it ended while another
    session in the same project is still running).
    """

    def __init__(self, store_dir, environ: dict | None = None):
        self.store_dir = Path(store_dir)
        self.environ = dict(environ if environ is not None else os.environ)
        self.sid = secrets.token_hex(8)
        self.token = secrets.token_hex(16)
        self._store = None
        self._keeper = None
        self._tcp: _TCPServer | None = None
        self._stop = threading.Event()
        self.hooks_served = 0

    # ------------------------------------------------------------ hooks
    def store(self):
        if self._store is None:
            from agent_memory.adapters.claude_code import _open
            self._store = _open(self.store_dir, self.environ)
            # SQLite checkpoints the WAL whenever the last connection closes. The store opens a connection
            # per operation, so in a long-lived process every close would checkpoint. One idle connection
            # held for the server's life keeps closes cheap. Checkpoints still happen automatically.
            import sqlite3
            self._keeper = sqlite3.connect(self._store._db, check_same_thread=False)
        return self._store

    def run_hook(self, agent: str, event: str, payload: bytes) -> str:
        from agent_memory.adapters import run
        with LOCK:
            try:
                store = self.store()
            except Exception:
                store = None   # the adapter's own path spools the failure and answers as usual
            out, _ = run(agent, event, payload, self.environ, store=store)
            self.hooks_served += 1
        return out

    # ------------------------------------------------------------ lifecycle
    def start(self) -> "SessionServer":
        self._tcp = _TCPServer(("127.0.0.1", 0), _Handler)
        self._tcp.owner = self   # type: ignore[attr-defined]
        threading.Thread(target=self._tcp.serve_forever, name="amem-session-server", daemon=True).start()
        self._claim_if_free()
        threading.Thread(target=self._watch, name="amem-session-server-watch", daemon=True).start()
        return self

    @property
    def port(self) -> int:
        return self._tcp.server_address[1] if self._tcp else 0

    def owns_file(self) -> bool:
        info = read_server_file(self.store_dir)
        return bool(info and info["sid"] == self.sid)

    def _claim_if_free(self) -> bool:
        if self.owns_file():
            return True
        if ping(self.store_dir):
            return False
        path = server_file(self.store_dir)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"server.{os.getpid()}.{self.sid}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(f"{self.port} {self.sid} {self.token} {os.getpid()}\n")
            os.replace(tmp, path)
            return True
        except OSError as err:
            print(f"agent-memory: session server not published: {err}", file=sys.stderr)
            return False

    def _watch(self) -> None:
        while not self._stop.wait(TAKEOVER_EVERY):
            self._claim_if_free()

    def stop(self) -> None:
        self._stop.set()
        if self.owns_file():
            try:
                server_file(self.store_dir).unlink()
            except OSError:
                pass
        if self._tcp is not None:
            self._tcp.shutdown()
            self._tcp.server_close()
        if self._keeper is not None:
            self._keeper.close()
            self._keeper = None


def serve_until_stdin_closes(store_dir, environ: dict | None = None, stdin=None) -> int:
    """`amem serve`: run the session server until the parent (the agent's plugin) closes our stdin."""
    srv = SessionServer(store_dir, environ).start()
    print(f"{PROTOCOL} serving {srv.port}", flush=True)
    try:
        for _ in (stdin or sys.stdin):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    return 0


__all__ = ["LOCK", "SessionServer", "forward", "ping", "read_server_file", "server_file",
           "serve_until_stdin_closes"]
