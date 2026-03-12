# Timezone Conventions

## Golden Rules

1. **Store UTC, Display Local** -- All stored timestamps and tool parameters use UTC. Convert to ET only for display.
2. **Use IANA timezone identifiers** -- Always use `"America/New_York"` instead of hand-rolled DST heuristics.
3. **Never hard-code UTC offsets** -- Use timezone libraries (`chrono-tz`, `zoneinfo`, `date-fns-tz`) that consult the IANA tz database.

## Data Flow

```
User (sees ET) -> Frontend (converts ET->UTC) -> Agent/MCP (UTC) -> Rust Backend (UTC internally, ET for display)
                                                                         |
                                                                         v
                                                                  Parquet files (UTC nanoseconds)
```

## Per-Component Conventions

### Rust Backend (UPQ Service)

- All internal timestamps are UTC nanoseconds since epoch
- Use `chrono-tz` crate with `America/New_York` for ET conversions
- Expiry anchor: 16:00 ET = `chrono_tz::America::New_York` conversion to UTC
- `ns_to_date_string()`: converts UTC ns to ET date string using `chrono-tz`

### Python Agent (`infra/playground/agent.py`)

- System prompt instructs LLM to use UTC for all tool parameters
- Display time uses `zoneinfo.ZoneInfo("America/New_York")` (stdlib, zero deps)
- Current simulation time shown as both UTC and ET in system prompt

### MCP Server (`mcp/server.py`)

- All datetime parameters in tool docstrings are documented as UTC
- Examples include UTC label: `"2024-01-15T14:30:00" (09:30 ET)`

### Frontend (`dashboard-web`)

- Uses `date-fns-tz` with `"America/New_York"` for ET-to-UTC conversion
- `datetime-local` inputs display ET, stored values are UTC ISO strings
- No hand-rolled DST offset calculations

## DST Transition Handling

- US Eastern DST transitions:
  - Spring forward: Second Sunday of March at 02:00 ET
  - Fall back: First Sunday of November at 02:00 ET
- All DST logic is delegated to IANA tz database libraries
- Test coverage includes exact DST boundary dates

## Adding New Components

When adding a new service or component:

1. Accept UTC timestamps in APIs
2. Use the appropriate IANA timezone library for the language
3. Add DST boundary tests (March spring-forward, November fall-back)
4. Document the timezone convention in the component's README
