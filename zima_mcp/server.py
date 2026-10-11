"""zima-mcp: let an AI assistant look after a ZimaBlade (or any Docker host) over plain SSH.

Every tool runs one read-only command over SSH, except zima_restart_container, which only
touches containers you list in ZIMA_RESTART_ALLOWLIST. Nothing is installed on the box.

Scope matches what a normal ZimaOS user can do: docker works without sudo (the user is in the
docker group), sudo needs a password the agent does not have. So there is no reboot, no
killing root processes and no editing system files, by design.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Docker container names: [a-zA-Z0-9][a-zA-Z0-9_.-]+ . Checking this (not only quoting) also stops a
# name like "--help" or "-f" being read as a docker flag.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass
class Config:
    host: str
    user: str
    port: int = 22
    key: str | None = None
    restart_allowlist: set[str] = field(default_factory=set)
    timeout: int = 20

    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        host, user = env.get("ZIMA_HOST", "").strip(), env.get("ZIMA_USER", "").strip()
        if not host or not user:
            raise SystemExit("zima-mcp: set ZIMA_HOST and ZIMA_USER (see config.example.env)")
        allow = {n.strip() for n in env.get("ZIMA_RESTART_ALLOWLIST", "").split(",") if n.strip()}
        bad = sorted(n for n in allow if not NAME_RE.match(n))
        if bad:
            raise SystemExit(f"zima-mcp: not valid container names in ZIMA_RESTART_ALLOWLIST: {bad}")
        return cls(host=host, user=user, port=int(env.get("ZIMA_SSH_PORT", "22")),
                   key=env.get("ZIMA_SSH_KEY") or None, restart_allowlist=allow,
                   timeout=int(env.get("ZIMA_SSH_TIMEOUT", "20")))

    def ssh_argv(self, remote_cmd: str) -> list[str]:
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                "-o", "StrictHostKeyChecking=accept-new", "-p", str(self.port)]
        if self.key:
            argv += ["-i", self.key]
        return argv + [f"{self.user}@{self.host}", remote_cmd]


def run_ssh(cfg: Config, remote_cmd: str, timeout: int | None = None) -> dict:
    """Run one command on the box. Never raises; returns {ok, exit_code, stdout, stderr}."""
    t = timeout or cfg.timeout
    try:
        p = subprocess.run(cfg.ssh_argv(remote_cmd), capture_output=True, text=True, timeout=t,
                           stdin=subprocess.DEVNULL)
        return {"ok": p.returncode == 0, "exit_code": p.returncode,
                "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": f"SSH command timed out after {t}s"}
    except OSError as e:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": str(e)}


def _text(obj) -> list[TextContent]:
    if isinstance(obj, str):
        return [TextContent(type="text", text=obj)]
    return [TextContent(type="text", text=json.dumps(obj, ensure_ascii=False, indent=2))]


def _out(r: dict) -> list[TextContent]:
    return _text(r["stdout"] if r["ok"] else r)


def _int(a: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(a.get(key, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _name(a: dict) -> str | None:
    n = str(a.get("container", "")).strip()
    return n if NAME_RE.match(n) else None


# ── tools ───────────────────────────────────────────────────────────────────────────────────────────
def t_load(cfg, a):
    return _out(run_ssh(cfg, "uptime"))


def t_top(cfg, a):
    n = _int(a, "count", 12, 1, 40)
    return _out(run_ssh(cfg, f"top -b -n1 -o %CPU | head -n {n + 7}"))


def t_docker_ps(cfg, a):
    return _out(run_ssh(cfg, "docker ps --format " + shlex.quote("table {{.Names}}\t{{.Status}}\t{{.Image}}")))


def t_docker_stats(cfg, a):
    fmt = "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
    return _out(run_ssh(cfg, "docker stats --no-stream --format " + shlex.quote(fmt), timeout=30))


def t_disk(cfg, a):
    return _out(run_ssh(cfg, "df -h"))


def t_logs(cfg, a):
    name = _name(a)
    if not name:
        return _text({"error": "container must be a Docker container name (letters, digits, _ . -)"})
    lines = _int(a, "lines", 80, 1, 500)
    return _out(run_ssh(cfg, f"docker logs --tail {lines} {shlex.quote(name)} 2>&1"))


def t_restart(cfg, a):
    name = _name(a)
    if not name:
        return _text({"error": "container must be a Docker container name (letters, digits, _ . -)"})
    if name not in cfg.restart_allowlist:
        return _text({"error": f"'{name}' is not in the restart allowlist",
                      "allowed": sorted(cfg.restart_allowlist),
                      "hint": "Add it to ZIMA_RESTART_ALLOWLIST (comma-separated) to permit restarts."})
    r = run_ssh(cfg, f"docker restart {shlex.quote(name)}", timeout=60)
    return _text({"restarted": name, "result": r["stdout"]} if r["ok"] else r)


_EMPTY = {"type": "object", "properties": {}}
TOOLS = [
    (Tool(name="zima_load", inputSchema=_EMPTY,
          description="Load average and uptime of the box. Quick check of whether it is busy."), t_load),
    (Tool(name="zima_top", description="Top processes by CPU. Use it to find what is pegging the CPU.",
          inputSchema={"type": "object", "properties": {
              "count": {"type": "integer", "description": "How many processes to show (default 12, max 40)."}}}),
     t_top),
    (Tool(name="zima_docker_ps", inputSchema=_EMPTY,
          description="List running Docker containers with status and image."), t_docker_ps),
    (Tool(name="zima_docker_stats", inputSchema=_EMPTY,
          description="One snapshot of CPU and memory per container. Best tool for finding the culprit."),
     t_docker_stats),
    (Tool(name="zima_disk", inputSchema=_EMPTY, description="Disk usage (df -h)."), t_disk),
    (Tool(name="zima_container_logs", description="Tail recent logs for one named container.",
          inputSchema={"type": "object", "required": ["container"], "properties": {
              "container": {"type": "string", "description": "Container name, e.g. immich-server."},
              "lines": {"type": "integer", "description": "Lines to tail (default 80, max 500)."}}}),
     t_logs),
    (Tool(name="zima_restart_container",
          description="Restart one named container. Only containers in ZIMA_RESTART_ALLOWLIST are allowed.",
          inputSchema={"type": "object", "required": ["container"], "properties": {
              "container": {"type": "string", "description": "Container name to restart."}}}),
     t_restart),
]


def build_server(cfg: Config) -> Server:
    server = Server("zima-mcp")
    handlers = {t.name: fn for t, fn in TOOLS}

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [t for t, _ in TOOLS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        fn = handlers.get(name)
        if not fn:
            return _text({"error": f"Unknown tool: {name}"})
        # ssh blocks; keep the event loop free so the client never times out the session
        return await asyncio.to_thread(fn, cfg, arguments or {})

    return server


async def _serve(cfg: Config) -> None:
    server = build_server(cfg)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="zima-mcp", description="MCP server for a ZimaBlade / Docker host over SSH.")
    ap.add_argument("--list-tools", action="store_true", help="print the tools and exit")
    ap.add_argument("--call", metavar="TOOL", help="run one tool once and print the result (for testing)")
    ap.add_argument("--arg", action="append", default=[], metavar="KEY=VALUE", help="argument for --call")
    a = ap.parse_args(argv)
    if a.list_tools:
        for t, _ in TOOLS:
            print(f"{t.name:24} {t.description}")
        return 0
    cfg = Config.from_env()
    if a.call:
        fn = dict((t.name, f) for t, f in TOOLS).get(a.call)
        if not fn:
            raise SystemExit(f"unknown tool {a.call}; try --list-tools")
        args = dict(x.split("=", 1) for x in a.arg)
        for c in fn(cfg, args):
            print(c.text)
        return 0
    asyncio.run(_serve(cfg))
    return 0
