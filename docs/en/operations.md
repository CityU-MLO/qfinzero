# Deployment and operations

> 中文: [docs/cn/operations.md](../cn/operations.md)

How to run QFinZero for a team: where it runs, how to put it behind HTTPS, what
to back up, how to upgrade and what to check.

## Topology

The hub is the only process that needs to be reachable. It authenticates every
request and proxies to the services, which listen on `127.0.0.1`:

```
browser, agents ──HTTPS──▶ reverse proxy ──▶ hub :19777 ──▶ UPQ :19350   (Rust, parquet)
                                               │      ├──▶ ESP :19330   (events, SQLite / MongoDB)
                                               │      ├──▶ PMB :19380   (paper broker)
                                               │      ├──▶ playground :19390, data console :19340
                                               │      └──▶ web UI :19300 (Next.js)
                                               └── /mcp (in process)
```

Do not publish the service ports. Anything reaching them directly bypasses
authentication.

## Running it

**Docker Compose** (one host). `docker-compose.yml` builds one image with the
hub, all services and the web UI. Data lives in the `qfz-data` volume mounted
at `/data`. To serve your own data, mount your data root at `/data` and remove
`QFZ_SAMPLE`.

```bash
export QFZ_ADMIN_PASSWORD='…'
docker compose up -d
docker compose logs -f qfinzero
```

**systemd** (from a checkout). `scripts/install-service.sh` installs a
user unit `qfinzero-hub` that restarts on failure and stops every child
cleanly:

```bash
./scripts/install-service.sh
systemctl --user status qfinzero-hub
```

Build UPQ in release mode (`cargo build --release -p upq-service` in
`infra/upq`) and the UI (`pnpm build` in `infra/dashboard-web`) before the first start.

## HTTPS and the reverse proxy

Terminate TLS at the proxy and forward `X-Forwarded-Proto` and
`X-Forwarded-For`. Session cookies are marked `Secure` when the request came
over HTTPS. MCP uses streaming HTTP responses, so turn off proxy buffering for
`/mcp/`, and list the public host name in `QFZ_PUBLIC_HOSTS`.

```nginx
server {
    listen 443 ssl;
    server_name qfz.example.com;
    # ssl_certificate …; ssl_certificate_key …;

    location / {
        proxy_pass http://127.0.0.1:19777;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 600s;
    }
    location /mcp/ {
        proxy_pass http://127.0.0.1:19777;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }
}
```

## Accounts

- Create the first admin with `QFZ_ADMIN_PASSWORD` (first start only), with
  `qfz-auth create-user <name> --role admin`, or through `/setup` with the
  one-time token printed in the log.
- Give people the least role they need: `viewer` reads, `researcher` also
  trades, runs research and uses MCP, `admin` also manages data and users.
- Agents use API keys. Create one key per agent or evaluation run so it can be
  revoked on its own; `qfz-auth list` shows when each key was last used.
- Set `QFZ_SECRET_KEY` explicitly if you run more than one hub against the same
  user database; otherwise each generates its own.

## What to back up

| path under `$QFZ_DATA_ROOT` | content | how to restore |
|---|---|---|
| `_state/auth.sqlite3`, `_state/auth_secret` | users, API key digests, cookie key | copy back; losing the secret signs everyone out |
| `_state/qfz.config.json` | vendor credentials and data console settings | copy back |
| `esp/*.sqlite3` | earnings, macro and SQLite news | copy back, or collect again |
| `upq/` | converted prices | rebuild with `qfz-data convert --all` from the raw files |

Raw vendor files are read in place and are not modified. Back them up as the
source of truth for `upq/`. SQLite files can be copied while the hub runs with
`sqlite3 <db> ".backup <file>"`.

Paper accounts and sessions live in PMB's memory and end when it restarts.
Export a session with `pmb_export_session` (or `GET /v1/sessions/{id}/export`)
to keep its record.

## Health and monitoring

- `GET /health` (public) returns the hub version and each child's state
  (`up`/`down`). A child that dies is reported as down; restart the hub to
  restart it.
- `GET /svc/upq/health/freshness` and `GET /svc/esp/esp/health/freshness` report the newest data per store.
- `qfz-data status` compares raw files with converted storage; the *Data* page shows the same.
- `qfz-bench oracle` against the sample dataset checks the whole stack end to end.

Logs go to standard output (Docker, journald). The hub logs each child's
start, health and exit.

## Upgrading

```bash
git pull
pip install -e ".[server,pipeline]"
(cd infra/upq && cargo build --release -p upq-service)
(cd infra/dashboard-web && pnpm install --frozen-lockfile && pnpm build)
systemctl --user restart qfinzero-hub      # or: docker compose up -d --build
```

The storage formats are versioned with the code. Read the
[changelog](../../CHANGELOG.md) before upgrading: a change that needs a
re-conversion or a new environment variable is listed there.

## Security checklist

- [ ] Only the hub (or the proxy in front of it) is reachable from outside.
- [ ] HTTPS in front of the hub; `QFZ_PUBLIC_HOSTS` set for `/mcp`.
- [ ] `QFZ_AUTH_MODE` is not `off`.
- [ ] `QFZ_ADMIN_PASSWORD` removed from the environment after the first start.
- [ ] Agents use their own API keys with the `researcher` role, not an admin key.
- [ ] Evaluations set `QFZ_REQUIRE_SESSION=1` so no data call escapes the time lock.
- [ ] `_state/` is backed up and readable only by the service user.

Report vulnerabilities as described in [SECURITY.md](../../SECURITY.md).
