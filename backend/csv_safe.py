"""SEC — CSV formula-injection guard used by every CSV writer in the codebase.

Excel and Google Sheets treat cells that start with ``=``, ``+``, ``-``, ``@``,
tab, or CR as formulas, which allows a hostile user-supplied field (name,
email, reason) to execute code the moment a staff member opens the export.
Prefixing such cells with a single quote makes the client render them as text.
"""
from typing import Any, Iterable, List

_CSV_FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(v: Any) -> Any:
    """Return a value safe to write into a CSV cell.

    Non-strings pass through untouched. Strings whose first character is a
    formula trigger get a leading single-quote so spreadsheet clients render
    the value as text instead of evaluating it.
    """
    if isinstance(v, str) and v and v[0] in _CSV_FORMULA_CHARS:
        return "'" + v
    return v


def safe_row(values: Iterable[Any]) -> List[Any]:
    """Apply :func:`sanitize_cell` to every value in a row."""
    return [sanitize_cell(v) for v in values]
