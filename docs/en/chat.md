# Chat

> 中文: [docs/cn/chat.md](../cn/chat.md)

*Chat* is a research and trading assistant over the QFinZero tools (market data,
news and events, the paper broker). It runs on the model you pick under
*Settings*; the key stays in your browser and is sent with each request.

## Conversations

- **New chat** starts a conversation; the first message names it (rename it from
  the header or with the pencil in the list, double-click works too).
- The list on the left holds your conversations, newest first, grouped by day,
  with a search over titles and messages. Delete asks once more before it goes.
- Conversations are stored on the server (`$QFZ_DATA_ROOT/_state/playground.sqlite3`,
  or `PLAYGROUND_DB`) per signed-in user: nobody else sees them, admins included.
- A conversation remembers the simulation time it was last used at and continues
  there when you open it again. Tools never see data after that time.
- The address has the conversation (`/chat?thread=…`), so a reload or a link
  reopens it.

## Context management

Every turn the model gets the whole conversation rebuilt from the history:
your messages, its answers, and each tool call paired with its result.

- **Context window** (settings drawer) is the size the context is fitted into;
  set it to your model's window.
- Tool results are the bulky part. Results older than the last two answers are
  cut to about 1,500 characters; recent ones to about 24,000. The model can
  call the tool again for the rest.
- **Auto-compact**: when the estimate reaches 80% of the window, the oldest turns
  (all but the last two) are summarised by the model; the summary goes into the
  system prompt and those turns leave the context. They stay in the history and
  in exports. **Compact** in the header does it now, keeping only the last turn.
- The meter in the header shows the estimated context against the window, what
  it consists of, how many messages were compacted, and the input size the model
  reported for the last request.

## Stopping an answer

While the assistant answers, the send button becomes **■** (or press Esc). What
was written so far is kept and marked as stopped; tool calls that had not
finished are marked cancelled, and the next turn tells the model it was
interrupted. Closing the page does not stop an answer: it keeps running on the
server, the list shows a spinner, and opening the conversation shows its
progress until it ends.

## Tool calls

Each model step's tool calls collapse into one line, *Used upq_stock_daily · 2
calls · 117 ms*. Open it for the record of each call: arguments, result (a
table for row data, or JSON) and timing.

**Run** (under an answer, or from an open tool line) opens the run inspector:

- **Flow**: the turn as a graph, your message → model step → the tools it
  called (parallel calls side by side) → the next step → the answer, and below
  it a timeline of model steps and tool calls on one time axis. Click a node or a
  bar for its input, output or text.
- **Record**: every step in order with its text and calls.

## Export

**Export** downloads the conversation as Markdown, with tool calls (input and
output in collapsible `<details>` blocks) or as text only. A compacted
conversation includes its summary.

## API

The playground service (`:19390`, proxied at `/api/playground`) scopes every call
to the `x-qfz-user` the hub sets.

| method | path | |
|---|---|---|
| `GET` | `/threads?q=` | your conversations |
| `POST` | `/threads` | a new, empty conversation |
| `GET` | `/threads/{id}` | messages with their steps; `running` and the `live` partial turn |
| `PATCH` / `DELETE` | `/threads/{id}` | rename / delete |
| `POST` | `/chat` | send a message (`thread_id` omitted: new conversation); SSE events `turn_start`, `context`, `compacted`, `step_start`, `llm_chunk`, `step_end`, `tool_start`, `tool_end`, then `done`, `interrupted` or `error` with the stored message |
| `POST` | `/threads/{id}/interrupt` | stop the running answer |
| `GET` | `/threads/{id}/context?budget=` | context estimate |
| `POST` | `/threads/{id}/compact` | summarise older turns now (needs the model fields) |
| `GET` | `/threads/{id}/export?tools=` | Markdown |
