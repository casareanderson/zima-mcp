#!/usr/bin/env bash
# Follows docs/SETUP.md on a GitHub runner. The runner plays both parts: it is the computer running
# the AI client AND the "ZimaBlade" (SSH to localhost, Docker without sudo, a real nginx container).
# Steps 2-4 of the guide are proven here; ZimaOS specifics and client config files are not (see SETUP.md).
set -euo pipefail
say() { printf '\n== %s\n' "$*"; }
fail() { echo "SETUP-CHECK FAILED: $*" >&2; exit 1; }

say "stand-in box: sshd + a key that logs in without a password (guide step 2)"
if ! command -v sshd >/dev/null; then sudo apt-get update -qq && sudo apt-get install -y -qq openssh-server; fi
sudo mkdir -p /run/sshd && (sudo systemctl start ssh 2>/dev/null || sudo /usr/sbin/sshd)
mkdir -p ~/.ssh && chmod 700 ~/.ssh
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$USER@localhost" docker ps >/dev/null \
  || fail "ssh + docker without a password did not work"
docker rm -f demo-web >/dev/null 2>&1 || true
docker run -d --name demo-web nginx:alpine >/dev/null

say "install (guide step 3) - from this checkout so CI tests the commit, not main"
python3 -m pip install -q pipx && python3 -m pipx ensurepath >/dev/null
python3 -m pipx install --force . >/dev/null
export PATH="$HOME/.local/bin:$PATH"
n=$(zima-mcp --list-tools | wc -l); [ "$n" -eq 7 ] || fail "expected 7 tools, got $n"

say "try it from the terminal (guide step 4)"
export ZIMA_HOST=localhost ZIMA_USER="$USER" ZIMA_RESTART_ALLOWLIST=demo-web
zima-mcp --call zima_load | grep -q "load average" || fail "zima_load"
zima-mcp --call zima_docker_ps | grep -q demo-web || fail "zima_docker_ps did not list demo-web"
zima-mcp --call zima_docker_stats | grep -q demo-web || fail "zima_docker_stats"
zima-mcp --call zima_disk | grep -q Filesystem || fail "zima_disk"
zima-mcp --call zima_container_logs --arg container=demo-web --arg lines=5 >/dev/null || fail "logs"

say "the safety net (guide step 6)"
zima-mcp --call zima_restart_container --arg container=demo-web | grep -q '"restarted": "demo-web"' || fail "allowlisted restart"
zima-mcp --call zima_restart_container --arg container=reverse-proxy | grep -q "not in the restart allowlist" || fail "allowlist"
zima-mcp --call zima_container_logs --arg 'container=--help' | grep -q "must be a Docker container name" || fail "name check"

say "a real MCP client over stdio"
python3 -m pipx runpip zima-mcp install -q anyio >/dev/null
"$(python3 -m pipx environment --value PIPX_LOCAL_VENVS)/zima-mcp/bin/python" - <<'PY'
import asyncio, os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
    p = StdioServerParameters(command="zima-mcp", args=[], env=dict(os.environ))
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            assert len((await s.list_tools()).tools) == 7
            out = (await s.call_tool("zima_docker_ps", {})).content[0].text
            assert "demo-web" in out, out
asyncio.run(main())
print("MCP stdio session OK")
PY
docker rm -f demo-web >/dev/null
say "setup-check passed"
