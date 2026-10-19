# 部署与运维

> English: [docs/en/operations.md](../en/operations.md)

如何为团队运行 QFinZero：部署在哪里、如何放到 HTTPS 之后、需要备份什么、如何升级以及需要检查什么。

## 拓扑

只有 hub 需要对外可达。它对每个请求做身份认证，再代理到只监听 `127.0.0.1` 的各个服务：

```
浏览器、agent ──HTTPS──▶ 反向代理 ──▶ hub :19777 ──▶ UPQ :19350   (Rust, parquet)
                                        │      ├──▶ ESP :19330   (事件, SQLite / MongoDB)
                                        │      ├──▶ PMB :19380   (模拟券商)
                                        │      ├──▶ playground :19390, 数据控制台 :19340
                                        │      └──▶ 网页界面 :19300 (Next.js)
                                        └── /mcp (进程内)
```

不要对外开放各服务的端口，直接访问它们会绕过身份认证。

## 运行方式

**Docker Compose**（单机）。`docker-compose.yml` 构建一个包含 hub、所有服务和网页界面的镜像，
数据保存在挂载到 `/data` 的 `qfz-data` 数据卷中。要使用自己的数据，把数据根目录挂载到 `/data`
并去掉 `QFZ_SAMPLE`。

```bash
export QFZ_ADMIN_PASSWORD='…'
docker compose up -d
docker compose logs -f qfinzero
```

**systemd**（从源码目录运行）。`scripts/install-service.sh` 会安装一个用户级服务 `qfinzero-hub`，
失败时自动重启，停止时干净地结束所有子进程：

```bash
./scripts/install-service.sh
systemctl --user status qfinzero-hub
```

首次启动前，先以 release 模式构建 UPQ（在 `infra/upq` 中运行 `cargo build --release -p upq-service`），
并构建网页界面（在 `infra/dashboard-web` 中运行 `pnpm build`）。

## HTTPS 与反向代理

在代理上终止 TLS，并转发 `X-Forwarded-Proto` 和 `X-Forwarded-For`。请求经 HTTPS 时，
session cookie 会带 `Secure` 标记。MCP 使用流式 HTTP 响应，所以要对 `/mcp/` 关闭代理缓冲，
并在 `QFZ_PUBLIC_HOSTS` 中列出公网主机名。

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

## 账号

- 创建首个管理员：用 `QFZ_ADMIN_PASSWORD`（仅首次启动）、`qfz-auth create-user <name> --role admin`，
  或在 `/setup` 页面输入日志中打印的一次性令牌。
- 只给每个人所需的最低角色：`viewer` 只读；`researcher` 还可以交易、做研究和使用 MCP；
  `admin` 还可以管理数据和用户。
- agent 使用 API 密钥。为每个 agent 或每次评测单独创建密钥，便于单独吊销；
  `qfz-auth list` 可以看到每个密钥最近一次使用的时间。
- 如果多个 hub 共用同一个用户数据库，请显式设置 `QFZ_SECRET_KEY`，否则每个 hub 会各自生成。

## 需要备份的内容

| `$QFZ_DATA_ROOT` 下的路径 | 内容 | 恢复方式 |
|---|---|---|
| `_state/auth.sqlite3`、`_state/auth_secret` | 用户、API 密钥摘要、cookie 密钥 | 复制回去；丢失密钥会让所有人退出登录 |
| `_state/qfz.config.json` | 供应商凭证和数据控制台设置 | 复制回去 |
| `esp/*.sqlite3` | 财报、宏观数据和 SQLite 新闻 | 复制回去，或重新采集 |
| `upq/` | 转换后的价格 | 用 `qfz-data convert --all` 从原始文件重建 |

供应商原始文件是原地读取的，不会被修改，请把它们作为 `upq/` 的数据源备份。SQLite 文件可以在 hub
运行时用 `sqlite3 <db> ".backup <file>"` 复制。

模拟账户和会话保存在 PMB 的内存中，PMB 重启后即结束。要保留记录，请用 `pmb_export_session`
（或 `GET /v1/sessions/{id}/export`）导出会话。

## 健康检查与监控

- `GET /health`（公开）返回 hub 版本和每个子服务的状态（`up`/`down`）。子服务退出后会显示为 down，
  重启 hub 即可重启它。
- `GET /svc/upq/health/freshness` 和 `GET /svc/esp/esp/health/freshness` 报告各存储最新数据的时间。
- `qfz-data status` 对比原始文件与已转换的存储；*数据* 页面显示同样的信息。
- 在样本数据集上运行 `qfz-bench oracle`，可端到端检查整套服务。

日志输出到标准输出（Docker、journald）。hub 会记录每个子服务的启动、健康状态和退出。

## 升级

```bash
git pull
pip install -e ".[server,pipeline]"
(cd infra/upq && cargo build --release -p upq-service)
(cd infra/dashboard-web && pnpm install --frozen-lockfile && pnpm build)
systemctl --user restart qfinzero-hub      # 或：docker compose up -d --build
```

存储格式随代码一起演进。升级前请阅读 [更新日志](../../CHANGELOG.md)：需要重新转换数据或新增环境变量的改动都会列在其中。

## 文档中心

`/docs` 是公开页面，由 Web UI 提供：

- **指南** 是仓库里的 markdown，列在 `docs/index.json` 中（中英文；没有中文文件的页面显示英文）。
- **API 参考** 和 **MCP 工具** 由 `docs/api/reference.json` 渲染，这个文件从服务本身生成：UPQ 的 `docs/upq/openapi.yaml`、ESP 和 PMB 的 FastAPI schema，以及 `mcp/server.py` 中注册的工具。修改接口或工具后运行 `python -m qfinzero.docsgen`；文件过期时测试会失败。
- 搜索（`⌘K` 或 `/`）覆盖指南章节、接口和工具。已登录的读者可以在接口页面用自己的会话发送 GET 请求和 ESP 查询。

hub 自身的 OpenAPI schema（`/auth` 路由）在 `/svc/openapi`。

## 安全检查清单

- [ ] 只有 hub（或其前面的代理）可以从外部访问。
- [ ] hub 前有 HTTPS；为 `/mcp` 设置了 `QFZ_PUBLIC_HOSTS`。
- [ ] `QFZ_AUTH_MODE` 不是 `off`。
- [ ] 首次启动后已从环境中移除 `QFZ_ADMIN_PASSWORD`。
- [ ] agent 使用各自的 `researcher` 角色 API 密钥，而不是管理员密钥。
- [ ] 评测时设置 `QFZ_REQUIRE_SESSION=1`，确保所有数据调用都受时间锁约束。
- [ ] `_state/` 已备份，且只有服务用户可以读取。

安全漏洞的报告方式见 [SECURITY.md](../../SECURITY.md)。
