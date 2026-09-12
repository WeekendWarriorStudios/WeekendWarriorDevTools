#!/usr/bin/env python3
"""Local web server for the Weekend Warrior Dev Tools UI.

Stdlib only - no pip install, matching the rest of this repo's system-Python tools. Serves the
static page in tools/ui/web/ and a small JSON API the page uses to discover and run tools:

    GET  /api/tools               current manifest (scans once at startup)
    POST /api/scan                re-scan tools/ now, return the fresh manifest
    POST /api/run                 {id, entryFunction?, params} -> {runId}, starts the tool
    GET  /api/stream/<runId>      Server-Sent Events: live stdout/stderr lines, then a done event
    POST /api/cancel/<runId>      kill a running tool

Why a server at all, instead of a plain static HTML page: a browser page cannot launch a
PowerShell process or a Python script on this machine - running a tool is the entire point of
this UI, so something outside the browser sandbox has to do it. This process is that something.
It only ever runs the specific script + arguments the page's Run button asked for, built from the
manifest scan_tools.py already parsed (see build_command below) - it does not evaluate arbitrary
text from the page.

Usage:
    python server.py                    # serve on http://127.0.0.1:8756, open a browser
    python server.py --port 9000 --no-browser
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_tools  # noqa: E402

UI_DIR = Path(__file__).resolve().parent
TOOLS_ROOT = UI_DIR.parent
WEB_DIR = UI_DIR / "web"
DEV_TOOLS_ROOT = TOOLS_ROOT.parent  # .../<ProjectRoot>/WeekendWarriorDevTools


def _detect_project_root() -> Path:
    """Mirror the same "three levels up from tools/<category>/script, with a submodule-nesting
    fallback" convention every PS1 tool uses to find <ProjectRoot> from its own location. The
    scripts locate this themselves from $PSScriptRoot regardless of cwd, so this only matters
    as a sane working directory for the child process, not for correctness."""
    candidate = DEV_TOOLS_ROOT.parent
    if not any(candidate.glob("*.uproject")):
        parent = candidate.parent
        if any(parent.glob("*.uproject")):
            candidate = parent
    return candidate


PROJECT_ROOT = _detect_project_root()

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


# --------------------------------------------------------------------------------------
# In-memory manifest cache + run tracking
# --------------------------------------------------------------------------------------

class ManifestCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._manifest: dict | None = None

    def rescan(self) -> dict:
        manifest = scan_tools.build_manifest(TOOLS_ROOT)
        with self._lock:
            self._manifest = manifest
        return manifest

    def get(self) -> dict:
        with self._lock:
            if self._manifest is None:
                return self.rescan()
            return self._manifest

    def find_tool(self, tool_id: str) -> dict | None:
        manifest = self.get()
        for t in manifest["tools"]:
            if t["id"] == tool_id:
                return t
        return None


class Run:
    def __init__(self, run_id: str, tool: dict, proc: subprocess.Popen):
        self.id = run_id
        self.tool = tool
        self.proc = proc
        self.events: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.done = threading.Event()
        self.exit_code: int | None = None
        self.started_at = time.time()


RUNS: dict[str, Run] = {}
RUNS_LOCK = threading.Lock()
CACHE = ManifestCache()


# --------------------------------------------------------------------------------------
# Command construction - one function per tool "kind". This is the only code that turns
# user-submitted form values into an actual command line; see each builder for the escaping
# rules that keep it that way rather than a shell-injection footgun.
# --------------------------------------------------------------------------------------

class RunRequestError(ValueError):
    """A problem with the run request itself (bad params, unknown tool) - reported to the UI,
    not a tool failure."""


def _ps_string_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _ps_literal(value, ui_type: str) -> str:
    if ui_type == "bool":
        return "$true" if value else "$false"
    if ui_type in ("int",):
        return str(int(value))
    if ui_type in ("float",):
        return repr(float(value))
    if ui_type == "string[]":
        items = value if isinstance(value, list) else [v for v in str(value).splitlines() if v.strip()]
        return "@(" + ", ".join(_ps_string_literal(v) for v in items) + ")"
    if ui_type == "json":
        return _ps_string_literal(json.dumps(value) if not isinstance(value, str) else value)
    return _ps_string_literal(value)


def build_powershell_command(tool: dict, params: dict) -> tuple[list[str], str]:
    script_path = TOOLS_ROOT / tool["relPath"]
    parts = [f"& {_ps_string_literal(str(script_path))}"]
    for spec in tool.get("params", []):
        name = spec["name"]
        if name not in params or params[name] in (None, ""):
            if spec["type"] == "bool" and name in params:
                pass  # explicit False is meaningful for a switch, handled below
            else:
                continue
        value = params.get(name)
        if spec["type"] == "bool":
            parts.append(f"-{name}:{_ps_literal(bool(value), 'bool')}")
        else:
            parts.append(f"-{name} {_ps_literal(value, spec['type'])}")
    command = " ".join(parts)
    argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command]
    return argv, command


def _py_arg_value(value, ui_type: str) -> str:
    if ui_type == "json" and not isinstance(value, str):
        return json.dumps(value)
    return str(value)


def build_python_cli_command(tool: dict, params: dict) -> tuple[list[str], str]:
    script_path = TOOLS_ROOT / tool["relPath"]
    argv = [_pick_python(), str(script_path)]
    for spec in tool.get("params", []):
        name = spec["name"]
        if name not in params or params[name] in (None, ""):
            continue
        value = params[name]
        flag = spec.get("flags", [f"--{name}"])[0] if spec.get("flags") else f"--{name}"
        long_flag = next((f for f in spec.get("flags", []) if f.startswith("--")), flag)
        if spec["type"] == "bool":
            if value:
                argv.append(long_flag)
        elif spec["type"] == "string[]":
            items = value if isinstance(value, list) else [v for v in str(value).splitlines() if v.strip()]
            argv.append(long_flag)
            argv.extend(items)
        else:
            argv.append(long_flag)
            argv.append(_py_arg_value(value, spec["type"]))
    for spec in tool.get("positionals", []):
        name = spec["name"]
        value = params.get(name)
        if value in (None, ""):
            continue
        if spec["type"] == "string[]":
            items = value if isinstance(value, list) else [v for v in str(value).splitlines() if v.strip()]
            argv.extend(items)
        else:
            argv.append(_py_arg_value(value, spec["type"]))
    return argv, " ".join(_display_quote(a) for a in argv)


def _display_quote(arg: str) -> str:
    return arg if arg and " " not in arg and '"' not in arg else '"' + arg.replace('"', '\\"') + '"'


def _pick_python() -> str:
    # Prefer the interpreter already running this server; fall back to the Windows launcher.
    if sys.executable:
        return sys.executable
    for candidate in ("py", "python", "python3"):
        return candidate
    return "python"


def _py_repr_for_call(value, ui_type: str) -> str:
    if ui_type == "json":
        try:
            parsed = value if not isinstance(value, str) else json.loads(value)
        except Exception:
            parsed = value
        return repr(parsed)
    if ui_type == "bool":
        return "True" if value else "False"
    if ui_type == "int":
        return repr(int(value))
    if ui_type == "float":
        return repr(float(value))
    if ui_type == "string[]":
        items = value if isinstance(value, list) else [v for v in str(value).splitlines() if v.strip()]
        return repr(items)
    return repr(str(value))


def build_python_editor_snippet(tool: dict, entry_function: str, params: dict) -> str:
    """Build a small Python source snippet that loads the target module by file path (sidestepping
    hyphenated filenames like validate-asset-data.py, which can't be `import`ed by name) and calls
    the chosen entry function with the submitted arguments. This snippet is what actually runs
    inside the editor, via ue_remote_exec.py --file."""
    entry = next((ef for ef in tool.get("entryFunctions", []) if ef["name"] == entry_function), None)
    if entry is None:
        raise RunRequestError(f"Unknown entry function '{entry_function}' for {tool['id']}")

    script_path = TOOLS_ROOT / tool["relPath"]
    kwargs = []
    for spec in entry["params"]:
        name = spec["name"]
        if name not in params or params[name] in (None, ""):
            if spec["required"]:
                raise RunRequestError(f"Missing required parameter '{name}'")
            continue
        kwargs.append(f"{name}={_py_repr_for_call(params[name], spec['type'])}")

    module_var = "_wwdt_mod"
    lines = [
        "import importlib.util as _wwdt_ilu",
        f"_wwdt_spec = _wwdt_ilu.spec_from_file_location({tool['name']!r}, {str(script_path)!r})",
        f"{module_var} = _wwdt_ilu.module_from_spec(_wwdt_spec)",
        f"_wwdt_spec.loader.exec_module({module_var})",
        f"_wwdt_result = {module_var}.{entry_function}({', '.join(kwargs)})",
        "print('[dev-tools-ui] result:', _wwdt_result)",
    ]
    return "\n".join(lines)


def build_command(tool: dict, params: dict, entry_function: str | None) -> tuple[list[str], str, Path | None]:
    """Returns (argv, display_command, temp_file_to_clean_up_or_None)."""
    if tool["kind"] == "powershell":
        argv, display = build_powershell_command(tool, params)
        return argv, display, None
    if tool["kind"] == "python-cli":
        argv, display = build_python_cli_command(tool, params)
        return argv, display, None
    if tool["kind"] == "python-editor":
        entry_function = entry_function or next(
            (ef["name"] for ef in tool.get("entryFunctions", []) if ef["isPrimary"]), None
        )
        if not entry_function:
            raise RunRequestError("This tool has no runnable entry function.")
        snippet = build_python_editor_snippet(tool, entry_function, params)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="wwdt_run_", delete=False, encoding="utf-8"
        )
        tmp.write(snippet)
        tmp.close()
        remote_exec = TOOLS_ROOT / "python" / "editor" / "ue_remote_exec.py"
        argv = [_pick_python(), str(remote_exec), "--file", tmp.name]
        display = f"python ue_remote_exec.py --file <generated: {tool['relPath']} :: {entry_function}(...)>"
        return argv, display, Path(tmp.name)
    raise RunRequestError(f"Unknown tool kind: {tool['kind']}")


# --------------------------------------------------------------------------------------
# Run execution
# --------------------------------------------------------------------------------------

def start_run(tool: dict, params: dict, entry_function: str | None) -> Run:
    argv, display_command, temp_file = build_command(tool, params, entry_function)
    run_id = uuid.uuid4().hex

    proc = subprocess.Popen(
        argv,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    run = Run(run_id, tool, proc)
    run.events.put(("cmd", display_command))

    def pump():
        try:
            for line in proc.stdout:
                run.events.put(("line", line.rstrip("\n")))
        except Exception as exc:
            run.events.put(("line", f"[dev-tools-ui] error reading output: {exc}"))
        finally:
            exit_code = proc.wait()
            run.exit_code = exit_code
            run.events.put(("exit", str(exit_code)))
            run.done.set()
            if temp_file is not None:
                try:
                    temp_file.unlink(missing_ok=True)
                except Exception:
                    pass

    threading.Thread(target=pump, daemon=True).start()
    with RUNS_LOCK:
        RUNS[run_id] = run
    return run


def cancel_run(run_id: str) -> bool:
    with RUNS_LOCK:
        run = RUNS.get(run_id)
    if not run or run.done.is_set():
        return False
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(run.proc.pid), "/T", "/F"],
                capture_output=True, check=False,
            )
        else:
            run.proc.terminate()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "WWDToolsUI/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[server] {self.address_string()} - {fmt % args}\n")

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, rel_path: str):
        if rel_path in ("", "/"):
            rel_path = "index.html"
        safe = (WEB_DIR / rel_path.lstrip("/")).resolve()
        if WEB_DIR not in safe.parents and safe != WEB_DIR:
            self.send_error(403)
            return
        if not safe.is_file():
            self.send_error(404)
            return
        data = safe.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES.get(safe.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise RunRequestError(f"Invalid JSON body: {exc}")

    # -- routing -------------------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/tools":
            self._send_json(CACHE.get())
        elif parsed.path.startswith("/api/stream/"):
            self._handle_stream(parsed.path.rsplit("/", 1)[-1])
        else:
            self._send_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/scan":
                self._send_json(CACHE.rescan())
            elif parsed.path == "/api/run":
                self._handle_run()
            elif parsed.path.startswith("/api/cancel/"):
                run_id = parsed.path.rsplit("/", 1)[-1]
                ok = cancel_run(run_id)
                self._send_json({"cancelled": ok})
            else:
                self.send_error(404)
        except RunRequestError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=500)

    # -- handlers -------------------------------------------------------------------

    def _handle_run(self):
        body = self._read_json_body()
        tool_id = body.get("id")
        if not tool_id:
            raise RunRequestError("Missing 'id'")
        tool = CACHE.find_tool(tool_id)
        if tool is None:
            raise RunRequestError(f"Unknown tool id: {tool_id}")
        params = body.get("params") or {}
        entry_function = body.get("entryFunction")
        run = start_run(tool, params, entry_function)
        self._send_json({"runId": run.id})

    def _handle_stream(self, run_id: str):
        with RUNS_LOCK:
            run = RUNS.get(run_id)
        if run is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def emit(event, data):
            payload = f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")
            self.wfile.write(payload)
            self.wfile.flush()

        try:
            while True:
                try:
                    kind, value = run.events.get(timeout=1.0)
                except queue.Empty:
                    if run.done.is_set() and run.events.empty():
                        break
                    emit("ping", "")
                    continue
                if kind == "cmd":
                    emit("cmd", {"command": value})
                elif kind == "line":
                    emit("line", {"text": value})
                elif kind == "exit":
                    emit("done", {"exitCode": int(value)})
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass


def find_free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8756)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    port = find_free_port(args.port)
    CACHE.rescan()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Weekend Warrior Dev Tools UI running at {url}")
    print(f"Tools root: {TOOLS_ROOT}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
