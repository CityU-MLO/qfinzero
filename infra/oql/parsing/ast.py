"""
AST (Abstract Syntax Tree) structures for OQL.
- OrderSpec: column + direction (ASC/DESC)
- Condition : field comparison with optional role (L/S/F/B/C/P)
- QueryAST  : overall parsed structure
"""
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class OrderSpec:
    col: str
    direction: str = "DESC"  # ASC|DESC

@dataclass
class Condition:
    field: str
    op: str
    val: str
    role: Optional[str] = None  # L/S/F/B/C/P or None

@dataclass
class QueryAST:
    strategy: str
    ticker: str
    where: List[Condition] = field(default_factory=list)
    having: List[Condition] = field(default_factory=list)
    order: List[OrderSpec] = field(default_factory=list)
    limit: int = 10
