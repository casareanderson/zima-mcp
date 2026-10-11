# Setting up zima-mcp

This takes about 10 minutes. By the end, your AI assistant can check load, containers, disk and logs on your ZimaBlade, and restart the containers you choose.

**What CI proves and what it can't.** The steps marked ✅ are run on every change by [`scripts/setup-check.sh`](../scripts/setup-check.sh) on a GitHub runner, against a stand-in Docker host (SSH to localhost, a real `nginx` container). CI can't prove the ZimaOS-specific parts (your box's SSH settings, the `docker` group on ZimaOS) or your AI client's config file, because those live on your machines.

## 1. What you need

- A computer that runs your AI client (Claude Desktop, Claude Code, Cursor, or any client that runs MCP servers over stdio), with **Python 3.10 or newer** and the **`ssh`** command.
- A **ZimaBlade or any Linux box with Docker**, reachable over SSH from that computer.
- A **user on that box who can run `docker` without sudo.** On ZimaOS the normal user is in the `docker` group, so this works out of the box. On other Linux systems: `sudo usermod -aG docker <user>`, then log out and in again.

zima-mcp never asks for a sudo password and never needs root.

## 2. Make SSH log in without a password

zima-mcp runs `ssh` in `BatchMode`, so it can't type a password. Use a key:

```bash
# on the computer running your AI client (skip if you already have a key)
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
ssh-copy-id you@your-zima
```

Check it, and check Docker works for that user. This command must print a container table and must **not** ask for a password:

```bash
ssh -o BatchMode=yes you@your-zima docker ps
```

## 3. Install ✅

```bash
pipx install git+https://github.com/casareanderson/zima-mcp
zima-mcp --list-tools
```

You should see seven tools, from `zima_load` to `zima_restart_container`. No `pipx`? Use a virtualenv instead:

```bash
python3 -m venv ~/.venvs/zima-mcp
~/.venvs/zima-mcp/bin/pip install git+https://github.com/casareanderson/zima-mcp
~/.venvs/zima-mcp/bin/zima-mcp --list-tools
```

If you go the virtualenv route, use the full path (`~/.venvs/zima-mcp/bin/zima-mcp`) as the command in step 5.

## 4. Try it from the terminal ✅

```bash
export ZIMA_HOST=your-zima ZIMA_USER=you
zima-mcp --call zima_load
zima-mcp --call zima_docker_ps
zima-mcp --call zima_container_logs --arg container=immich-server --arg lines=20
```

`zima_load` prints one `uptime` line. If you get JSON with `"ok": false` instead, the `stderr` field says why. See [Common errors](#common-errors).

## 5. Add it to your AI client

Decide which containers the assistant may restart. Leave `ZIMA_RESTART_ALLOWLIST` empty to allow none. Restarting your reverse proxy, login service or tunnel can lock you out, so leave those off.

**Claude Code**

```bash
claude mcp add zima \
  -e ZIMA_HOST=your-zima -e ZIMA_USER=you \
  -e ZIMA_RESTART_ALLOWLIST=immich-server,immich-machine-learning \
  -- zima-mcp
claude mcp list
```

**Claude Desktop.** Settings → Developer → Edit Config opens `claude_desktop_config.json`. Add:

```json
{
  "mcpServers": {
    "zima": {
      "command": "zima-mcp",
      "env": {
        "ZIMA_HOST": "your-zima",
        "ZIMA_USER": "you",
        "ZIMA_RESTART_ALLOWLIST": "immich-server,immich-machine-learning"
      }
    }
  }
}
```

Restart Claude Desktop. Desktop apps often don't see your shell's `PATH`, so if it says the command isn't found, put the full path from `which zima-mcp` in `command`.

**Cursor.** Same JSON in `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project).

**Hermes Agent.** In `config.yaml`:

```yaml
mcp_servers:
  zima:
    command: /full/path/to/zima-mcp
    env:
      ZIMA_HOST: your-zima
      ZIMA_USER: you
      ZIMA_RESTART_ALLOWLIST: immich-server
    timeout: 30
```

**Anything else** that runs MCP servers over stdio: the command is `zima-mcp` with no arguments, and settings come from the environment variables in [config.example.env](../config.example.env).

## 6. Check it works

Ask your assistant: *"Use the zima tools: how busy is the box, and which container uses the most memory?"* It should call `zima_load` and `zima_docker_stats` and answer from real numbers.

Then try the safety net: *"Restart the container called reverse-proxy."* Unless it's on your allowlist, you should get "not in the restart allowlist" back, and nothing restarts.

## Common errors

| What you see | Why | Fix |
|---|---|---|
| `Permission denied (publickey,password)` | Key not installed for that user | Step 2: `ssh-copy-id you@your-zima` |
| `Host key verification failed` | The box's SSH key changed (reinstall, new IP owner) | `ssh-keygen -R your-zima`, then `ssh you@your-zima` once to accept the new key |
| `permission denied while trying to connect to the Docker daemon socket` | The user isn't in the `docker` group | `sudo usermod -aG docker you` on the box, then log out and in |
| `SSH command timed out after 20s` | Box asleep, wrong host, firewall | Check `ssh you@your-zima uptime` by hand. Raise `ZIMA_SSH_TIMEOUT` for slow links |
| `zima-mcp: set ZIMA_HOST and ZIMA_USER` | The env block didn't reach the server | Put both in your client's `env` block, not only in your shell |
| `container must be a Docker container name` | The name has spaces, `;`, `$` or starts with `-` | Use the exact name from `zima_docker_ps` |
| `top: unrecognized option` | Minimal BusyBox `top` without `-o` | Use `zima_docker_stats` instead; it doesn't need `top` |

## Updating

```bash
pipx upgrade zima-mcp        # or: ~/.venvs/zima-mcp/bin/pip install -U git+https://github.com/casareanderson/zima-mcp
```

Restart your AI client afterwards so it reloads the tools.

## Uninstalling

```bash
claude mcp remove zima        # Claude Code; for others delete the "zima" block from the config file
pipx uninstall zima-mcp
```

Nothing was installed on the box, so there's nothing to remove there. Remove the SSH key from `~/.ssh/authorized_keys` on the box if you only added it for this.
