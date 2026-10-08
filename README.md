# Yandex Tracker MCP

[![CI](https://github.com/skyfox-fur/yandex_tracker_mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/skyfox-fur/yandex_tracker_mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)

An [MCP](https://modelcontextprotocol.io/) server for [Yandex Tracker](https://tracker.yandex.ru/)
(API v3). It lets Claude and other MCP clients search, read and update issues, comment, move issues
between statuses, link them, log time, and download and attach files.

## Tools

**Read**

| Tool | Description |
|------|-------------|
| `whoami` | The user the token belongs to |
| `get_issue` | Issue by key, brief or full |
| `search_issues` | Search by Tracker query, queue or field filter (paginated) |
| `count_issues` | Number of issues matching a query |
| `get_comments` | Issue comments (cursor pagination) |
| `get_transitions` | Status transitions available for an issue |
| `get_links` | Links to other issues |
| `get_worklog` | Time tracking records |
| `list_queues` | Queues (paginated) |
| `get_queue` | Queue details with issue types and priorities |
| `list_users` | Organization users (paginated) |
| `list_fields` | Global issue fields |
| `list_attachments` | Files of an issue and its comments |
| `download_attachment` | Save an attachment to a local file and return its path |

**Write**

| Tool | Description |
|------|-------------|
| `create_issue` | Create an issue |
| `update_issue` | Update issue fields |
| `add_comment` | Add a comment, optionally mentioning users and attaching files |
| `attach_file` | Attach a local file to an issue |
| `edit_comment` | Replace a comment's text, optionally adding files |
| `delete_comment` | Delete a comment |
| `transition_issue` | Move an issue to another status |
| `link_issues` | Link two issues |
| `add_worklog` | Log time |

Write tools carry MCP `readOnlyHint` / `destructiveHint` annotations, and in read-only mode they
are not registered at all.

## Setup

### 1. Get an OAuth token

1. Create an app at <https://oauth.yandex.ru/client/new> with the **Tracker** scopes
   `tracker:read` and `tracker:write` (only `tracker:read` for read-only use).
   If asked for a Redirect URI, use `https://oauth.yandex.ru/verification_code`.
2. Copy the app's **ClientID** (the client secret is not needed) and open
   `https://oauth.yandex.ru/authorize?response_type=token&client_id=<ClientID>`.
3. Allow access; the page shows the token.

### 2. Find your organization ID

Open <https://tracker.yandex.ru/admin/orgs>:

- a **Yandex 360** organization has a numeric ID → `TRACKER_ORG_ID`;
- a **Yandex Cloud** organization → `TRACKER_CLOUD_ORG_ID`. You can also use an IAM token
  (`yc iam create-token`, valid for 12 hours) with `TRACKER_AUTH_TYPE=iam`.

### 3. Connect to Claude Code

With [uv](https://docs.astral.sh/uv/), no clone needed:

```bash
claude mcp add yandex-tracker --scope user -e TRACKER_TOKEN=<token> -e TRACKER_ORG_ID=<org_id> -- uvx --from git+https://github.com/skyfox-fur/yandex_tracker_mcp yandex-tracker-mcp
```

Or from a local clone:

```bash
git clone https://github.com/skyfox-fur/yandex_tracker_mcp.git
cd yandex_tracker_mcp
python -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip install -e .
claude mcp add yandex-tracker --scope user -e TRACKER_TOKEN=<token> -e TRACKER_ORG_ID=<org_id> -- "$PWD/.venv/bin/yandex-tracker-mcp"
```

Start a new session and ask Claude to call `whoami` to check the connection.

### Claude Desktop

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "yandex-tracker": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/skyfox-fur/yandex_tracker_mcp", "yandex-tracker-mcp"],
      "env": {
        "TRACKER_TOKEN": "<token>",
        "TRACKER_ORG_ID": "<org_id>"
      }
    }
  }
}
```

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `TRACKER_TOKEN` | yes | OAuth token, or an IAM token with `TRACKER_AUTH_TYPE=iam` |
| `TRACKER_ORG_ID` | one of | Yandex 360 organization ID |
| `TRACKER_CLOUD_ORG_ID` | one of | Yandex Cloud organization ID |
| `TRACKER_AUTH_TYPE` | no | `oauth` (default) or `iam` |
| `TRACKER_READ_ONLY` | no | `1`/`true`/`yes`/`on` hides all write tools |
| `TRACKER_API_URL` | no | API base URL, https only (default `https://api.tracker.yandex.net/v3`) |
| `TRACKER_DOWNLOAD_DIR` | no | Download directory; files go to `<dir>/<issue key>/` (default `<temp>/yandex-tracker-mcp-<user>`) |
| `TRACKER_UPLOAD_DIRS` | no | Extra directories files may be uploaded from (`:`-separated, `;` on Windows); not a drive root or home |
| `TRACKER_MAX_FILE_MB` | no | Size limit for downloads and uploads, MB (default `50`) |
| `TRACKER_ENV_FILE` | no | Path to a `.env` file with the variables above (see [`.env.example`](.env.example)) |

Invalid values are reported on stderr at startup, and the server exits. An unrecognized
`TRACKER_READ_ONLY` value is treated as read-only.

## Security

- Use a token with the least privileges you need, and `TRACKER_READ_ONLY=1` when you only read.
- Issue and comment texts can contain instructions aimed at the model (prompt injection). The server
  tells the client to treat them as data. Keep write tools behind your client's confirmation prompt.
- Arguments that go into URL paths are validated, so a tool cannot be steered to another API endpoint.
- Uploads, so that a prompt-injected issue cannot make the model send arbitrary local files:
  - Files may be uploaded only from the server's working directory, the download directory and
    `TRACKER_UPLOAD_DIRS`. The working directory counts only if it is narrower than a drive root or your
    home directory, because some clients start servers in `/` or `~`.
  - These are always refused: hidden files and directories (`.env`, `.ssh`, `.git`, Windows hidden or system
    files), typical secrets (`id_rsa`, `*.pem`, `*.key`, `credentials*`, `*.tfstate`, ...), `TRACKER_ENV_FILE`
    and alternate data streams.
  - Symlinks are resolved before the checks. The file is read right away and verified to be the file that was
    checked. Results list the local paths that were sent.
- Downloads are saved under a sanitized name in a per-user directory (`0700`, files `0600`) and never
  overwrite existing files. Risky extensions such as `.lnk`, `.scf` or `.bat` get a `.download` suffix.
  Downloaded content is untrusted input, like issue text.
- `.env` is read only from `TRACKER_ENV_FILE`, never from the working directory, so a foreign `.env`
  cannot redirect your token. The API URL must be https.
- API calls do not follow redirects. File downloads follow up to 3 https redirects to storage. Authorization and
  organization headers are not sent to other hosts.
- Never commit `.env` or tokens. `.env` is git-ignored.

## Development

```bash
pip install -e ".[dev]"
python -m pytest                       # no real API calls: HTTP is mocked
ruff check . && ruff format --check .
```

Project layout:

```
src/yandex_tracker_mcp/
  config.py      environment variables and validation
  client.py      shared HTTP client, error handling, path validation, upload/download
  files.py       upload policy and safe local file names
  formatting.py  compact views of Tracker objects, pagination
  server.py      MCP tools and the entry point
tests/           pytest suite
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add a tool, and [CHANGELOG.md](CHANGELOG.md) for history.

## License

[MIT](LICENSE) © [skyfox-fur](https://github.com/skyfox-fur)
