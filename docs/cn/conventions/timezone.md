> English: [../../en/conventions/timezone.md](../../en/conventions/timezone.md)

# 时区约定

## 黄金准则

1. **存储用 UTC，展示用本地时间** —— 所有存储的时间戳和工具参数都使用 UTC。仅在展示时才转换为 ET（美东时间）。
2. **使用 IANA 时区标识符** —— 始终使用 `"America/New_York"`，而不是自行编写的夏令时（DST）启发式判断。
3. **绝不硬编码 UTC 偏移量** —— 使用查询 IANA tz 数据库的时区库（`chrono-tz`、`zoneinfo`、`date-fns-tz`）。

## 数据流

```
User (sees ET) -> Frontend (converts ET->UTC) -> Agent/MCP (UTC) -> Rust Backend (UTC internally, ET for display)
                                                                         |
                                                                         v
                                                                  Parquet files (UTC nanoseconds)
```

## 各组件约定

### Rust 后端（UPQ Service）

- 所有内部时间戳均为自纪元起的 UTC 纳秒
- 使用 `chrono-tz` crate 配合 `America/New_York` 进行 ET 转换
- 到期锚点：16:00 ET = 通过 `chrono_tz::America::New_York` 转换为 UTC
- `ns_to_date_string()`：使用 `chrono-tz` 将 UTC 纳秒转换为 ET 日期字符串

### Python Agent（`infra/playground/agent.py`）

- 系统提示词指示 LLM 对所有工具参数使用 UTC
- 展示时间使用 `zoneinfo.ZoneInfo("America/New_York")`（标准库，零依赖）
- 系统提示词中将当前模拟时间同时以 UTC 和 ET 显示

### MCP Server（`mcp/server.py`）

- 工具 docstring 中的所有 datetime 参数均注明为 UTC
- 示例中包含 UTC 标注：`"2024-01-15T14:30:00" (09:30 ET)`

### 前端（`dashboard-web`）

- 使用 `date-fns-tz` 配合 `"America/New_York"` 进行 ET 到 UTC 的转换
- `datetime-local` 输入框展示 ET，存储的值为 UTC ISO 字符串
- 不使用自行编写的 DST 偏移计算

## 夏令时（DST）切换处理

- 美国东部 DST 切换：
  - 春季调快：3 月第二个星期日 02:00 ET
  - 秋季调慢：11 月第一个星期日 02:00 ET
- 所有 DST 逻辑均委托给 IANA tz 数据库库处理
- 测试覆盖包含精确的 DST 边界日期

## 新增组件

在新增服务或组件时：

1. 在 API 中接受 UTC 时间戳
2. 为该语言使用合适的 IANA 时区库
3. 添加 DST 边界测试（3 月春季调快、11 月秋季调慢）
4. 在该组件的 README 中记录时区约定
