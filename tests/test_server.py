import json
import subprocess

import pytest

from zima_mcp import server as S


@pytest.fixture
def cfg():
    return S.Config(host="192.0.2.10", user="zima", restart_allowlist={"immich-server"})


@pytest.fixture
def calls(monkeypatch):
    """Record every ssh argv instead of running it."""
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(S.subprocess, "run", fake_run)
    return seen


def text(result):
    return result[0].text


def test_config_needs_host_and_user():
    with pytest.raises(SystemExit):
        S.Config.from_env({})
    c = S.Config.from_env({"ZIMA_HOST": "nas.example.com", "ZIMA_USER": "zima",
                           "ZIMA_RESTART_ALLOWLIST": "a, b ,", "ZIMA_SSH_PORT": "2222"})
    assert c.restart_allowlist == {"a", "b"} and c.port == 2222


def test_config_rejects_bad_allowlist_names():
    with pytest.raises(SystemExit):
        S.Config.from_env({"ZIMA_HOST": "h", "ZIMA_USER": "u", "ZIMA_RESTART_ALLOWLIST": "ok,$(reboot)"})


def test_ssh_argv(cfg):
    cfg.key = "/k"
    argv = cfg.ssh_argv("uptime")
    assert argv[0] == "ssh" and "BatchMode=yes" in argv and argv[-2:] == ["zima@192.0.2.10", "uptime"]
    assert argv[argv.index("-i") + 1] == "/k"


def test_load_runs_uptime(cfg, calls):
    assert text(S.t_load(cfg, {})) == "ok"
    assert calls[0][-1] == "uptime"


@pytest.mark.parametrize("bad", ["", "--help", "-f", "a;reboot", "$(id)", "a b", "x" * 200, "../etc"])
def test_logs_rejects_unsafe_names(cfg, calls, bad):
    out = json.loads(text(S.t_logs(cfg, {"container": bad})))
    assert "error" in out and calls == []


def test_logs_clamps_lines_and_quotes(cfg, calls):
    S.t_logs(cfg, {"container": "immich-server", "lines": "99999"})
    assert calls[0][-1] == "docker logs --tail 500 immich-server 2>&1"
    S.t_logs(cfg, {"container": "immich-server", "lines": "lots"})
    assert calls[1][-1].startswith("docker logs --tail 80 ")


def test_top_count_clamped(cfg, calls):
    S.t_top(cfg, {"count": 1000})
    assert calls[0][-1].endswith("head -n 47")


def test_restart_needs_allowlist(cfg, calls):
    out = json.loads(text(S.t_restart(cfg, {"container": "authelia"})))
    assert "not in the restart allowlist" in out["error"] and calls == []
    out = json.loads(text(S.t_restart(cfg, {"container": "immich-server"})))
    assert out["restarted"] == "immich-server" and calls[0][-1] == "docker restart immich-server"


def test_ssh_failure_is_reported_not_raised(cfg, monkeypatch):
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)
    monkeypatch.setattr(S.subprocess, "run", boom)
    out = json.loads(text(S.t_disk(cfg, {})))
    assert out["ok"] is False and "timed out" in out["stderr"]


def test_no_tool_can_reboot_or_sudo(cfg, calls):
    for tool, fn in S.TOOLS:
        fn(cfg, {"container": "immich-server"})
    joined = " ".join(c[-1] for c in calls)
    assert "sudo" not in joined and "reboot" not in joined and "shutdown" not in joined


@pytest.mark.anyio
async def test_mcp_session_lists_and_calls(cfg, calls):
    from mcp.shared.memory import create_connected_server_and_client_session
    srv = S.build_server(cfg)
    async with create_connected_server_and_client_session(srv) as client:
        tools = await client.list_tools()
        assert len(tools.tools) == 7
        r = await client.call_tool("zima_disk", {})
        assert r.content[0].text == "ok"


def test_cli_list_tools(capsys):
    assert S.main(["--list-tools"]) == 0
    assert "zima_restart_container" in capsys.readouterr().out
