# Releasing zima-mcp

Releases are tag-driven and need no stored tokens: PyPI uses trusted publishing and the MCP Registry uses GitHub OIDC.

## One-time setup (owner, pypi.org)

1. Sign in at https://pypi.org (enable 2FA if asked).
2. Your account menu → **Your projects** → **Publishing** (https://pypi.org/manage/account/publishing/).
3. Under **Add a new pending publisher** pick **GitHub** and fill in:
   - PyPI Project Name: `zima-mcp`
   - Owner: `casareanderson`
   - Repository name: `zima-mcp`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
4. **Add**. The project is created on the first successful upload.

## Each release

1. Bump `version` in `pyproject.toml` and both `version` fields in `server.json`.
2. Commit, then `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. The `release` workflow runs the tests, builds, uploads to PyPI, waits for PyPI to show the version, then publishes `server.json` to the MCP Registry as `io.github.casareanderson/zima-mcp`.

The Registry checks ownership through the `mcp-name:` line in the README, which PyPI shows as the package description.
