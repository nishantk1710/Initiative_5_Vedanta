"""Cross-page table continuation detection for generic (non-line-item)
tables — see generic_tables.py/table_semantics.py for the per-page physical
reconstruction this operates on afterward.

A table split across a page break shows up as two independent physical
reconstructions: the earlier page's table (with its own real header row)
and the next page's table (usually with no NEW confident header of its
own, since the header only printed once). Left alone, the output would
show a bank statement's transactions, say, as two disconnected table
objects the frontend has to guess about merging. This module links them
back together deterministically, from each table's own real bbox/column
geometry — never guessed from page numbers or content, and never assuming
in advance which pages continue.

Both conditions below must hold for a pair to link, in this order:
  1. The earlier table's bbox reaches near the bottom of ITS OWN page's
     real rendered height (it plausibly ran out of page, not just ran out
     of rows) — checked against that page's actual height, never a
     hardcoded page size.
  2. The next page's table has the same column COUNT and each column's
     x-band lines up with the earlier table's, within a tolerance scaled
     to that page's own width. A genuinely different table that happens to
     share a column count but sits at different x-positions is not linked.

Only adjacent pages (page N -> page N+1) are ever considered, and each
table can extend at most one existing chain — no skip-linking, no
many-to-one merges.
"""

from collections import defaultdict

BOTTOM_MARGIN_FRACTION = 0.08  # bottom 8% of a page counts as "near the bottom"
COLUMN_X_TOLERANCE_FRACTION = 0.05  # relative to page width


def _is_near_bottom(table: dict, page_height: float | None) -> bool:
    if not page_height:
        return False
    return table["bbox"][3] >= page_height * (1 - BOTTOM_MARGIN_FRACTION)


def _columns_align(earlier: dict, later: dict, page_width: float | None) -> bool:
    e_bounds = earlier.get("column_bounds")
    l_bounds = later.get("column_bounds")
    if not e_bounds or not l_bounds or len(e_bounds) != len(l_bounds):
        return False
    if not page_width:
        return False

    tolerance = page_width * COLUMN_X_TOLERANCE_FRACTION
    for (e_lo, e_hi), (l_lo, l_hi) in zip(e_bounds, l_bounds):
        # The outermost column on either side legitimately has an infinite
        # bound (see generic_tables.py's _column_bands_from_row) — that's
        # not a real position to compare, so only the finite edge of an
        # edge column is checked.
        if e_lo not in (float("-inf"), float("inf")) and l_lo not in (float("-inf"), float("inf")):
            if abs(e_lo - l_lo) > tolerance:
                return False
        if e_hi not in (float("-inf"), float("inf")) and l_hi not in (float("-inf"), float("inf")):
            if abs(e_hi - l_hi) > tolerance:
                return False
    return True


def _is_continuation(earlier: dict, later: dict, page_heights: dict[int, float], page_widths: dict[int, float]) -> bool:
    if later["page"] != earlier["page"] + 1:
        return False
    if not _is_near_bottom(earlier, page_heights.get(earlier["page"])):
        return False
    return _columns_align(earlier, later, page_widths.get(earlier["page"]))


def _merge_chain(chain: list[dict]) -> dict:
    first = chain[0]
    merged_rows: list[list[str]] = []
    for t in chain:
        merged_rows.extend(t["rows"])
    return {
        **first,
        "pages": [t["page"] for t in chain],
        "rows": merged_rows,
        "row_count": len(merged_rows),
    }


def link_continuations(tables: list[dict], page_heights: dict[int, float], page_widths: dict[int, float]) -> list[dict]:
    """Returns a NEW list: continuation chains folded into one logical
    table with a `pages: [p1, p2, ...]` array; standalone tables pass
    through with `pages: [page]` added for a uniform shape. Never mutates
    the input list."""
    by_page: dict[int, list[dict]] = defaultdict(list)
    for t in tables:
        by_page[t["page"]].append(t)

    consumed_ids: set[str] = set()
    merged: list[dict] = []

    for t in sorted(tables, key=lambda t: (t["page"], t["bbox"][1])):
        if t["table_id"] in consumed_ids:
            continue

        chain = [t]
        current = t
        while True:
            candidates = [c for c in by_page.get(current["page"] + 1, []) if c["table_id"] not in consumed_ids]
            match = next((c for c in candidates if _is_continuation(current, c, page_heights, page_widths)), None)
            if match is None:
                break
            consumed_ids.add(match["table_id"])
            chain.append(match)
            current = match

        merged.append(_merge_chain(chain))

    return merged
