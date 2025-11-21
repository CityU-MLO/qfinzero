"""
OQL parser:
- Strips `--` comments
- Supports multi-column ORDER BY
- Operators: >, <, =, >=, <=, !=, ~ (approx)
- Keeps column name case as-is for better downstream matching
"""
import re
from typing import List
from parsing.ast import QueryAST, Condition, OrderSpec

_WHITESPACE = re.compile(r"\s+")
_AND_SPLIT = re.compile(r"\s+AND\s+", re.IGNORECASE)

def _strip_comments(q: str) -> str:
    """Remove inline and full-line `--` comments and normalize spaces."""
    lines = []
    for line in q.splitlines():
        if "--" in line:
            line = line.split("--", 1)[0]
        lines.append(line)
    return " ".join(lines)

class OQLParser:
    def parse(self, query: str) -> QueryAST:
        q = _strip_comments(query).strip()
        q = _WHITESPACE.sub(" ", q)

        # Main SQL-like skeleton (non-greedy capture for optional clauses)
        pattern = re.compile(
            r"""
            ^\s*SELECT\s+(?P<strategy>[A-Za-z_][A-Za-z0-9_]*)
            \s+FROM\s+(?P<ticker>[A-Za-z0-9\.\-_]+)
            (?:\s+WHERE\s+(?P<where>.*?))?
            (?:\s+HAVING\s+(?P<having>.*?))?
            (?:\s+ORDER\s+BY\s+(?P<order>.*?))?
            (?:\s+LIMIT\s+(?P<limit>\d+))?
            \s*$
            """,
            re.IGNORECASE | re.VERBOSE,
        )
        m = pattern.match(q)
        if not m:
            raise ValueError("Invalid OQL Syntax. Expected: SELECT ... FROM ... [WHERE ...] [HAVING ...] [ORDER BY ...] [LIMIT n]")

        strategy = m.group("strategy").upper()
        ticker = m.group("ticker").upper()
        where_str = (m.group("where") or "").strip()
        having_str = (m.group("having") or "").strip()
        order_str = (m.group("order") or "").strip()
        limit_str = (m.group("limit") or "").strip()

        where = self._parse_conditions(where_str, allow_role=True) if where_str else []
        having = self._parse_conditions(having_str, allow_role=False) if having_str else []
        order = self._parse_order(order_str) if order_str else []
        limit = int(limit_str) if limit_str else 10

        return QueryAST(strategy=strategy, ticker=ticker, where=where, having=having, order=order, limit=limit)

    def _parse_conditions(self, text: str, allow_role: bool) -> List[Condition]:
        """Parse conditions joined by AND. Role.Field or Field forms are supported."""
        if not text:
            return []
        parts = _AND_SPLIT.split(text)
        conds: List[Condition] = []

        # Role.Field OP Value
        role_pat = re.compile(
            r"""^(?P<role>[A-Za-z])\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)
                \s*(?P<op>>=|<=|!=|=|>|<|~)\s*
                (?P<val>[-+]?\d*\.?\d+|[A-Za-z]+)$""",
            re.VERBOSE,
        )

        # Field OP Value (no role)
        no_role_pat = re.compile(
            r"""^(?P<field>[A-Za-z_][A-Za-z0-9_]*)
                \s*(?P<op>>=|<=|!=|=|>|<|~)\s*
                (?P<val>[-+]?\d*\.?\d+)$""",
            re.VERBOSE,
        )

        for p in parts:
            s = p.strip()
            if not s:
                continue
            if allow_role:
                m = role_pat.match(s)
                if m:
                    conds.append(
                        Condition(
                            role=m.group("role").upper(),
                            field=m.group("field"),
                            op=m.group("op"),
                            val=m.group("val"),
                        )
                    )
                    continue
            m = no_role_pat.match(s)
            if m:
                conds.append(
                    Condition(
                        role=None,
                        field=m.group("field"),
                        op=m.group("op"),
                        val=m.group("val"),
                    )
                )
        return conds

    def _parse_order(self, text: str) -> List[OrderSpec]:
        """Parse 'col [ASC|DESC], col2 [ASC|DESC]' into a list of OrderSpec."""
        specs: List[OrderSpec] = []
        for item in text.split(","):
            s = item.strip()
            if not s:
                continue
            parts = s.split()
            col = parts[0]
            direction = parts[1].upper() if len(parts) > 1 else "DESC"
            if direction not in ("ASC", "DESC"):
                direction = "DESC"
            specs.append(OrderSpec(col=col, direction=direction))
        return specs
