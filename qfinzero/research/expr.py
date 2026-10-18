"""Factor expressions: a small, safe language compiled to DuckDB window SQL.

Agents and people write factors as one expression, for example::

    cs_rank(-pct(close, 15)) * cs_rank(ts_mean(volume, 30) / ts_mean(volume, 390))
    ts_zscore(close - vwap, 60)
    -ts_corr(ret, delta(volume, 1), 30)

The expression is parsed with Python's ``ast`` into a whitelist of nodes (no
attribute access, calls only to the functions below, no names but fields), so
it can be evaluated on behalf of an agent without running its code.

Point-in-time rules built into the language:

* every time-series operator only looks backwards: ``delay``/``delta``/``pct``
  need ``n >= 1``, windows end at the current bar;
* a window must be full (``n`` bars) or the value is NULL;
* by default windows reset each trading day (``cross_day=False``), so an
  intraday factor never mixes yesterday's bars in;
* ``cs_*`` operators rank across all tickers at the same minute.

Fields: ``open high low close volume transactions vwap ret minute`` and, when
quotes are joined, ``bid ask mid spread imbalance``. ``vwap`` is the bar's
typical price ``(high+low+close)/3``; ``ret`` is the 1-bar close return;
``minute`` is minutes since 09:30 ET.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

BAR_FIELDS = {"open", "high", "low", "close", "volume", "transactions", "vwap", "ret", "minute"}
QUOTE_FIELDS = {"bid", "ask", "mid", "spread", "imbalance"}

# name -> (kind, n_args incl. window length) ; kind: ts | ts2 | lag | cs | scalar
FUNCTIONS: dict[str, tuple[str, int]] = {
    "ts_mean": ("ts", 2), "ts_sum": ("ts", 2), "ts_std": ("ts", 2),
    "ts_min": ("ts", 2), "ts_max": ("ts", 2), "ts_zscore": ("ts", 2),
    "ts_corr": ("ts2", 3), "ts_cov": ("ts2", 3),
    "delay": ("lag", 2), "delta": ("lag", 2), "pct": ("lag", 2),
    "cs_rank": ("cs", 1), "cs_zscore": ("cs", 1), "cs_demean": ("cs", 1),
    "abs": ("scalar", 1), "log": ("scalar", 1), "sign": ("scalar", 1), "sqrt": ("scalar", 1),
    "max": ("scalar", 2), "min": ("scalar", 2),
}
MAX_WINDOW = 5000
MAX_OPS = 24


class ExprError(ValueError):
    """The expression is malformed or uses something not allowed."""


@dataclass
class Compiled:
    """SQL layers that add column ``factor`` to a panel relation."""
    layers: list[str]                 # each: SELECT *, ... FROM {prev}
    fields: set[str]
    needs_quotes: bool
    max_window: int
    ops: int = 0

    def sql(self, panel: str) -> str:
        """Full query over relation/CTE named ``panel``."""
        ctes = [f"_l0 AS (SELECT * FROM {panel})"]
        for i, layer in enumerate(self.layers, start=1):
            ctes.append(f"_l{i} AS ({layer.format(prev=f'_l{i-1}')})")
        return f"WITH {', '.join(ctes)} SELECT * FROM _l{len(self.layers)}"


@dataclass
class _State:
    cross_day: bool
    layers: list[str] = field(default_factory=list)
    fields: set[str] = field(default_factory=set)
    n_cols: int = 0
    max_window: int = 1
    ops: int = 0

    def new_col(self) -> str:
        self.n_cols += 1
        return f"_c{self.n_cols}"

    def materialize(self, sql: str) -> str:
        """Put a scalar SQL expression into its own column; return the name."""
        name = self.new_col()
        self.layers.append(f"SELECT *, {sql} AS {name} FROM {{prev}}")
        return name

    def part(self) -> str:
        return "PARTITION BY ticker" if self.cross_day else "PARTITION BY ticker, trade_date"


def _int_arg(node: ast.AST, what: str) -> int:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    raise ExprError(f"{what} must be an integer literal")


def _window(n: int, fn: str) -> int:
    if n < 1:
        raise ExprError(f"{fn}: window/lag must be >= 1 (no look-ahead)")
    if n > MAX_WINDOW:
        raise ExprError(f"{fn}: window must be <= {MAX_WINDOW}")
    return n


def _compile(node: ast.AST, st: _State) -> str:
    """Return a SQL expression valid in the current (last) layer."""
    if isinstance(node, ast.Expression):
        return _compile(node.body, st)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        return repr(float(node.value))
    if isinstance(node, ast.Name):
        if node.id not in BAR_FIELDS | QUOTE_FIELDS:
            raise ExprError(f"unknown field {node.id!r}; fields: "
                            f"{', '.join(sorted(BAR_FIELDS | QUOTE_FIELDS))}")
        st.fields.add(node.id)
        return node.id
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _compile(node.operand, st)
        return f"(-({inner}))" if isinstance(node.op, ast.USub) else inner
    if isinstance(node, ast.BinOp):
        ops = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
        op = ops.get(type(node.op))
        if op is None:
            raise ExprError("only + - * / are allowed")
        a, b = _compile(node.left, st), _compile(node.right, st)
        if op == "/":
            return f"(({a}) / nullif(({b}), 0))"
        return f"(({a}) {op} ({b}))"
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise ExprError(f"unknown function; allowed: {', '.join(sorted(FUNCTIONS))}")
        if node.keywords:
            raise ExprError("keyword arguments are not allowed")
        fn = node.func.id
        kind, nargs = FUNCTIONS[fn]
        if len(node.args) != nargs:
            raise ExprError(f"{fn} takes {nargs} argument(s)")
        st.ops += 1
        if st.ops > MAX_OPS:
            raise ExprError(f"expression too complex (> {MAX_OPS} functions)")
        if kind == "scalar":
            args = [_compile(a, st) for a in node.args]
            sql_fn = {"abs": "abs", "log": "ln", "sign": "sign", "sqrt": "sqrt",
                      "max": "greatest", "min": "least"}[fn]
            if fn == "log":
                return f"ln(nullif(greatest({args[0]}, 0), 0))"
            if fn == "sqrt":
                return f"sqrt(greatest({args[0]}, 0))"
            return f"{sql_fn}({', '.join(args)})"
        if kind == "cs":
            col = st.materialize(_compile(node.args[0], st))
            out = st.new_col()
            win = f"OVER (PARTITION BY window_start)"
            expr = {
                "cs_rank": f"CASE WHEN {col} IS NULL THEN NULL ELSE percent_rank() OVER "
                           f"(PARTITION BY window_start, ({col} IS NULL) ORDER BY {col}) END",
                "cs_zscore": f"({col} - avg({col}) {win}) / nullif(stddev_samp({col}) {win}, 0)",
                "cs_demean": f"({col} - avg({col}) {win})",
            }[fn]
            st.layers.append(f"SELECT *, {expr} AS {out} FROM {{prev}}")
            return out
        if kind == "lag":
            n = _window(_int_arg(node.args[1], f"{fn} lag"), fn)
            col = st.materialize(_compile(node.args[0], st))
            st.max_window = max(st.max_window, n + 1)
            out = st.new_col()
            lag = f"lag({col}, {n}) OVER ({st.part()} ORDER BY window_start)"
            expr = {"delay": lag, "delta": f"({col} - {lag})",
                    "pct": f"({col} / nullif({lag}, 0) - 1)"}[fn]
            st.layers.append(f"SELECT *, {expr} AS {out} FROM {{prev}}")
            return out
        # rolling windows
        n = _window(_int_arg(node.args[-1], f"{fn} window"), fn)
        st.max_window = max(st.max_window, n)
        frame = f"OVER ({st.part()} ORDER BY window_start ROWS BETWEEN {n - 1} PRECEDING AND CURRENT ROW)"
        if kind == "ts2":
            x = st.materialize(_compile(node.args[0], st))
            y = st.materialize(_compile(node.args[1], st))
            agg = {"ts_corr": f"corr({x}, {y})", "ts_cov": f"covar_samp({x}, {y})"}[fn]
            cnt = f"count({x}) {frame}"
            expr = f"CASE WHEN {cnt} = {n} THEN {agg} {frame} END"
        else:
            x = st.materialize(_compile(node.args[0], st))
            cnt = f"count({x}) {frame}"
            agg = {
                "ts_mean": f"avg({x}) {frame}", "ts_sum": f"sum({x}) {frame}",
                "ts_std": f"stddev_samp({x}) {frame}", "ts_min": f"min({x}) {frame}",
                "ts_max": f"max({x}) {frame}",
                "ts_zscore": f"({x} - avg({x}) {frame}) / nullif(stddev_samp({x}) {frame}, 0)",
            }[fn]
            expr = f"CASE WHEN {cnt} = {n} THEN {agg} END"
        out = st.new_col()
        st.layers.append(f"SELECT *, {expr} AS {out} FROM {{prev}}")
        return out
    raise ExprError(f"unsupported syntax: {type(node).__name__}")


def compile_expr(expression: str, cross_day: bool = False) -> Compiled:
    """Compile ``expression`` into SQL layers producing column ``factor``."""
    if not expression or len(expression) > 2000:
        raise ExprError("expression must be 1-2000 characters")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise ExprError(f"syntax error: {e.msg}") from e
    st = _State(cross_day=cross_day)
    final = _compile(tree, st)
    st.layers.append(f"SELECT *, CAST({final} AS DOUBLE) AS factor FROM {{prev}}")
    return Compiled(layers=st.layers, fields=st.fields,
                    needs_quotes=bool(st.fields & QUOTE_FIELDS),
                    max_window=st.max_window, ops=st.ops)
