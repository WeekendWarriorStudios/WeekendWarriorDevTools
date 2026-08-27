#!/usr/bin/env python3
"""Drive a running Unreal Editor from outside it, over the Python Remote Execution protocol.

Unlike everything under ``tools/python/assets`` and ``tools/python/level``, this script runs in
*system* Python, not inside the editor. It speaks the UDP-discovery + TCP-command protocol that
the Python Editor Script Plugin exposes, so a terminal, a CI job, or an agent can execute editor
Python against an already-open project without restarting it or clicking through the UI.

Enable it once, in the editor:
    Edit > Project Settings > Plugins > Python
      [x] Enable Remote Execution
    (writes ``PythonScriptPluginSettings.PythonRemoteExecution=True`` to
     ``Saved/Config/WindowsEditor/EditorPerProjectUserSettings.ini``)

Command line
------------
    python ue_remote_exec.py --ping
    python ue_remote_exec.py --eval "unreal.SystemLibrary.get_engine_version()"
    python ue_remote_exec.py --stmt "unreal.log('hello')"
    python ue_remote_exec.py --file author_pose_search_schemas.py
    python ue_remote_exec.py --file build_databases.py --json

As a module
-----------
    from ue_remote_exec import UnrealRemoteSession

    with UnrealRemoteSession() as ue:
        print(ue.eval("len(unreal.EditorAssetLibrary.list_assets('/Game'))"))
        ue.exec_file("my_editor_script.py")

Exit codes: 0 success, 1 remote command failed, 2 no editor found, 3 usage error.

Protocol reference: Engine/Plugins/Experimental/PythonScriptPlugin/Content/Python/remote_execution.py
and PythonScriptRemoteExecution.cpp. Protocol version 1.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import uuid

PROTOCOL_VERSION = 1
PROTOCOL_MAGIC = "ue_py"

TYPE_PING = "ping"
TYPE_PONG = "pong"
TYPE_OPEN_CONNECTION = "open_connection"
TYPE_CLOSE_CONNECTION = "close_connection"
TYPE_COMMAND = "command"
TYPE_COMMAND_RESULT = "command_result"

# Execution modes; these strings must match LexToString for EPythonCommandExecutionMode.
MODE_EXEC_FILE = "ExecuteFile"            # multi-statement script or a file path
MODE_EXEC_STATEMENT = "ExecuteStatement"  # one statement, result printed
MODE_EVAL_STATEMENT = "EvaluateStatement" # one expression, result returned

DEFAULT_MULTICAST_GROUP = ("239.0.0.1", 6766)
DEFAULT_MULTICAST_BIND = "127.0.0.1"
DEFAULT_MULTICAST_TTL = 0
DEFAULT_COMMAND_ENDPOINT = ("127.0.0.1", 6776)


class RemoteExecError(RuntimeError):
    """Raised when the editor could not be reached, or refused the command channel."""


def _message(type_: str, source: str, dest: str | None = None, data: dict | None = None) -> bytes:
    obj = {"version": PROTOCOL_VERSION, "magic": PROTOCOL_MAGIC, "type": type_, "source": source}
    if dest:
        obj["dest"] = dest
    if data:
        obj["data"] = data
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _parse(raw: bytes) -> dict | None:
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if obj.get("version") != PROTOCOL_VERSION or obj.get("magic") != PROTOCOL_MAGIC:
        return None
    return obj


class UnrealRemoteSession:
    """A discovery + command session against one running editor.

    Args:
        multicast_group: group endpoint the editor listens on. Must match the plugin setting.
        multicast_bind: adapter the UDP socket binds to. Must match the plugin setting.
        command_endpoint: the TCP address *this* process listens on; the editor dials back to it.
        node_id: pick a specific editor when several projects are open (see :meth:`discover`).
    """

    def __init__(
        self,
        multicast_group=DEFAULT_MULTICAST_GROUP,
        multicast_bind=DEFAULT_MULTICAST_BIND,
        multicast_ttl=DEFAULT_MULTICAST_TTL,
        command_endpoint=DEFAULT_COMMAND_ENDPOINT,
        node_id: str | None = None,
    ):
        self.multicast_group = multicast_group
        self.multicast_bind = multicast_bind
        self.multicast_ttl = multicast_ttl
        self.command_endpoint = command_endpoint
        self.target_node_id = node_id

        self._self_id = str(uuid.uuid4())
        self._udp: socket.socket | None = None
        self._listen: socket.socket | None = None
        self._channel: socket.socket | None = None
        self._remote_node_id: str | None = None

    # ---- lifecycle ----------------------------------------------------

    def __enter__(self) -> "UnrealRemoteSession":
        self.open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def open(self) -> None:
        self._open_udp()
        nodes = self.discover()
        if not nodes:
            raise RemoteExecError(
                "No Unreal Editor found on the multicast group. Check that the editor is running, "
                "that Python Remote Execution is enabled in Project Settings > Plugins > Python, "
                "and that the multicast group/bind address match."
            )
        node = self._select(nodes)
        self._remote_node_id = node["node_id"]
        self._open_channel()

    def close(self) -> None:
        if self._channel:
            try:
                self._channel.close()
            finally:
                self._channel = None
        if self._udp and self._remote_node_id:
            try:
                self._broadcast(TYPE_CLOSE_CONNECTION, self._remote_node_id)
            except OSError:
                pass
        for sock_attr in ("_listen", "_udp"):
            sock = getattr(self, sock_attr)
            if sock:
                try:
                    sock.close()
                finally:
                    setattr(self, sock_attr, None)
        self._remote_node_id = None

    # ---- discovery ----------------------------------------------------

    def _open_udp(self) -> None:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        udp.bind((self.multicast_bind, self.multicast_group[1]))
        udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.multicast_ttl)
        udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.multicast_bind))
        udp.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_ADD_MEMBERSHIP,
            socket.inet_aton(self.multicast_group[0]) + socket.inet_aton(self.multicast_bind),
        )
        udp.settimeout(0.1)
        self._udp = udp

    def _broadcast(self, type_: str, dest: str | None = None, data: dict | None = None) -> None:
        assert self._udp is not None
        self._udp.sendto(_message(type_, self._self_id, dest, data), self.multicast_group)

    def discover(self, timeout: float = 2.0) -> list[dict]:
        """Ping the group and collect every editor that answers within ``timeout`` seconds."""
        if self._udp is None:
            self._open_udp()
        found: dict[str, dict] = {}
        deadline = time.monotonic() + timeout
        next_ping = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_ping:
                self._broadcast(TYPE_PING)
                next_ping = now + 1.0
            try:
                raw, _addr = self._udp.recvfrom(8192)
            except (socket.timeout, TimeoutError):
                continue
            msg = _parse(raw)
            if not msg or msg.get("type") != TYPE_PONG or msg.get("source") == self._self_id:
                continue
            data = dict(msg.get("data") or {})
            data["node_id"] = msg["source"]
            found[msg["source"]] = data
            if self.target_node_id and msg["source"] == self.target_node_id:
                break
        return list(found.values())

    def _select(self, nodes: list[dict]) -> dict:
        if self.target_node_id:
            for node in nodes:
                if node["node_id"] == self.target_node_id:
                    return node
            raise RemoteExecError(f"No editor with node id {self.target_node_id!r}. Run --ping to list.")
        if len(nodes) > 1:
            listing = "\n".join(
                f"  {n['node_id']}  {n.get('project_name', '?')}  ({n.get('engine_version', '?')})" for n in nodes
            )
            raise RemoteExecError(
                f"{len(nodes)} editors are running; pass --node to choose one:\n{listing}"
            )
        return nodes[0]

    # ---- command channel ----------------------------------------------

    def _open_channel(self) -> None:
        listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        listen.bind(self.command_endpoint)
        listen.listen(1)
        listen.settimeout(5.0)
        self._listen = listen

        # The editor dials back to us. Re-broadcast between attempts: the first invite can land
        # while the editor is mid-tick and busy enough to drop it.
        for _attempt in range(6):
            self._broadcast(
                TYPE_OPEN_CONNECTION,
                self._remote_node_id,
                {"command_ip": self.command_endpoint[0], "command_port": self.command_endpoint[1]},
            )
            try:
                self._channel = listen.accept()[0]
                self._channel.setblocking(True)
                return
            except (socket.timeout, TimeoutError):
                continue
        raise RemoteExecError(
            "The editor never opened the command channel. It is usually busy (compiling shaders, "
            "cooking, or blocked on a modal dialog) — retry once it is idle."
        )

    def run(self, command: str, exec_mode: str = MODE_EXEC_FILE, unattended: bool = True) -> dict:
        """Execute ``command`` in the editor and return the raw protocol result dict.

        The dict carries ``success`` (bool), ``result`` (str) and ``output`` (list of
        ``{type, output}`` log records).
        """
        if self._channel is None:
            raise RemoteExecError("Session is not open. Use `with UnrealRemoteSession() as ue:`.")
        self._channel.sendall(
            _message(
                TYPE_COMMAND,
                self._self_id,
                self._remote_node_id,
                {"command": command, "unattended": unattended, "exec_mode": exec_mode},
            )
        )
        # A long asset-authoring script can return far more than one recv() worth of JSON, so
        # accumulate until the buffer parses rather than trusting a single read.
        buffer = b""
        while True:
            chunk = self._channel.recv(65536)
            if not chunk:
                raise RemoteExecError("The editor closed the command channel mid-command.")
            buffer += chunk
            msg = _parse(buffer)
            if msg is None:
                continue
            if msg.get("type") != TYPE_COMMAND_RESULT:
                buffer = b""
                continue
            return msg.get("data") or {}

    # ---- convenience --------------------------------------------------

    def eval(self, expression: str):
        """Evaluate a single expression and return its repr as a string. Raises on failure."""
        return self._checked(self.run(expression, MODE_EVAL_STATEMENT))["result"]

    def exec_statement(self, statement: str):
        return self._checked(self.run(statement, MODE_EXEC_STATEMENT))["result"]

    def exec_script(self, source: str) -> dict:
        """Execute a multi-statement Python script (passed as source text)."""
        return self._checked(self.run(source, MODE_EXEC_FILE))

    def exec_file(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as handle:
            return self.exec_script(handle.read())

    @staticmethod
    def _checked(result: dict) -> dict:
        if not result.get("success", False):
            raise RemoteExecError(_format_failure(result))
        return result


def _format_failure(result: dict) -> str:
    lines = [str(result.get("result", "<no result>"))]
    for record in result.get("output") or []:
        lines.append(f"  [{record.get('type', 'Log')}] {record.get('output', '').rstrip()}")
    return "\n".join(lines)


def _print_output(result: dict) -> None:
    for record in result.get("output") or []:
        stream = sys.stderr if record.get("type") in ("Error", "Warning") else sys.stdout
        print(record.get("output", "").rstrip(), file=stream)
    payload = result.get("result")
    if payload not in (None, "", "None"):
        print(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute Python inside a running Unreal Editor.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Command line")[1] if "Command line" in __doc__ else None,
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--ping", action="store_true", help="list running editors and exit")
    action.add_argument("--file", metavar="PATH", help="execute a local .py file's contents in the editor")
    action.add_argument("--stmt", metavar="CODE", help="execute a single statement")
    action.add_argument("--eval", metavar="EXPR", dest="eval_expr", help="evaluate an expression and print it")

    parser.add_argument("--node", help="target a specific editor node id (see --ping)")
    parser.add_argument("--json", action="store_true", help="emit the raw protocol result as JSON")
    parser.add_argument("--attended", action="store_true", help="allow the editor to show UI/dialogs")
    parser.add_argument("--multicast-group", default=f"{DEFAULT_MULTICAST_GROUP[0]}:{DEFAULT_MULTICAST_GROUP[1]}")
    parser.add_argument("--multicast-bind", default=DEFAULT_MULTICAST_BIND)
    parser.add_argument("--command-port", type=int, default=DEFAULT_COMMAND_ENDPOINT[1])
    args = parser.parse_args(argv)

    try:
        group_host, group_port = args.multicast_group.rsplit(":", 1)
        group = (group_host, int(group_port))
    except ValueError:
        print(f"--multicast-group must be HOST:PORT, got {args.multicast_group!r}", file=sys.stderr)
        return 3

    session = UnrealRemoteSession(
        multicast_group=group,
        multicast_bind=args.multicast_bind,
        command_endpoint=(DEFAULT_COMMAND_ENDPOINT[0], args.command_port),
        node_id=args.node,
    )

    if args.ping:
        try:
            nodes = session.discover()
        finally:
            session.close()
        if args.json:
            print(json.dumps(nodes, indent=2))
        elif not nodes:
            print("No editors responded.", file=sys.stderr)
        else:
            for node in nodes:
                print(
                    f"{node['node_id']}  {node.get('project_name', '?')}  "
                    f"{node.get('engine_version', '?')}  {node.get('project_root', '')}"
                )
        return 0 if nodes else 2

    try:
        with session as ue:
            if args.file:
                with open(args.file, "r", encoding="utf-8") as handle:
                    source = handle.read()
                result = ue.run(source, MODE_EXEC_FILE, unattended=not args.attended)
            elif args.stmt:
                result = ue.run(args.stmt, MODE_EXEC_STATEMENT, unattended=not args.attended)
            else:
                result = ue.run(args.eval_expr, MODE_EVAL_STATEMENT, unattended=not args.attended)
    except RemoteExecError as err:
        print(str(err), file=sys.stderr)
        return 2
    except OSError as err:
        print(f"Socket error talking to the editor: {err}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_output(result)
    return 0 if result.get("success", False) else 1


if __name__ == "__main__":
    sys.exit(main())
