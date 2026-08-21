"""Cross-page table continuation linking — every link decision must come
from real bbox/column geometry, never from page order or content alone."""

from continuation import link_continuations


def _table(table_id, page, bottom_y, headers, column_bounds, semantic_confidence=0.0):
    return {
        "table_id": table_id,
        "page": page,
        "bbox": [0.0, 100.0, 900.0, bottom_y],
        "headers": headers,
        "rows": [["r1c1", "r1c2"]],
        "row_count": 1,
        "semantic_role": "unknown" if semantic_confidence == 0.0 else "bank_transactions",
        "semantic_confidence": semantic_confidence,
        "column_bounds": column_bounds,
    }


PAGE_HEIGHT = 1000.0
PAGE_WIDTH = 900.0
COLS = [[-float("inf"), 300.0], [300.0, 600.0], [600.0, float("inf")]]


def test_links_a_genuine_continuation_across_adjacent_pages():
    earlier = _table("1:t:0", 1, bottom_y=970.0, headers=["Date", "Desc", "Amount"], column_bounds=COLS)
    later = _table("2:t:0", 2, bottom_y=400.0, headers=["", "", ""], column_bounds=COLS)

    result = link_continuations([earlier, later], {1: PAGE_HEIGHT, 2: PAGE_HEIGHT}, {1: PAGE_WIDTH, 2: PAGE_WIDTH})

    assert len(result) == 1
    assert result[0]["pages"] == [1, 2]
    assert result[0]["row_count"] == 2
    assert result[0]["rows"] == [["r1c1", "r1c2"], ["r1c1", "r1c2"]]


def test_does_not_link_when_earlier_table_is_not_near_the_bottom():
    """A table that ends mid-page genuinely finished — the next page's
    table is a new one, not a continuation."""
    earlier = _table("1:t:0", 1, bottom_y=500.0, headers=["Date", "Desc", "Amount"], column_bounds=COLS)
    later = _table("2:t:0", 2, bottom_y=400.0, headers=["", "", ""], column_bounds=COLS)

    result = link_continuations([earlier, later], {1: PAGE_HEIGHT, 2: PAGE_HEIGHT}, {1: PAGE_WIDTH, 2: PAGE_WIDTH})

    assert len(result) == 2
    assert {tuple(t["pages"]) for t in result} == {(1,), (2,)}


def test_does_not_link_when_column_counts_differ():
    earlier = _table("1:t:0", 1, bottom_y=970.0, headers=["Date", "Desc", "Amount"], column_bounds=COLS)
    different_cols = [[-float("inf"), 450.0], [450.0, float("inf")]]
    later = _table("2:t:0", 2, bottom_y=400.0, headers=["A", "B"], column_bounds=different_cols)

    result = link_continuations([earlier, later], {1: PAGE_HEIGHT, 2: PAGE_HEIGHT}, {1: PAGE_WIDTH, 2: PAGE_WIDTH})

    assert len(result) == 2


def test_does_not_link_when_column_positions_differ_beyond_tolerance():
    earlier = _table("1:t:0", 1, bottom_y=970.0, headers=["Date", "Desc", "Amount"], column_bounds=COLS)
    shifted_cols = [[-float("inf"), 500.0], [500.0, 700.0], [700.0, float("inf")]]  # shifted well past tolerance
    later = _table("2:t:0", 2, bottom_y=400.0, headers=["", "", ""], column_bounds=shifted_cols)

    result = link_continuations([earlier, later], {1: PAGE_HEIGHT, 2: PAGE_HEIGHT}, {1: PAGE_WIDTH, 2: PAGE_WIDTH})

    assert len(result) == 2


def test_does_not_link_across_non_adjacent_pages():
    earlier = _table("1:t:0", 1, bottom_y=970.0, headers=["Date", "Desc", "Amount"], column_bounds=COLS)
    later = _table("3:t:0", 3, bottom_y=400.0, headers=["", "", ""], column_bounds=COLS)  # page 3, not 2

    result = link_continuations([earlier, later], {1: PAGE_HEIGHT, 3: PAGE_HEIGHT}, {1: PAGE_WIDTH, 3: PAGE_WIDTH})

    assert len(result) == 2


def test_never_assumes_which_pages_continue_in_advance():
    """Three unrelated single-page tables (different documents' worth of
    content, never near a page bottom) must all stay standalone."""
    t1 = _table("1:t:0", 1, bottom_y=300.0, headers=["A"], column_bounds=[[-float("inf"), float("inf")]])
    t2 = _table("2:t:0", 2, bottom_y=300.0, headers=["B"], column_bounds=[[-float("inf"), float("inf")]])
    t3 = _table("3:t:0", 3, bottom_y=300.0, headers=["C"], column_bounds=[[-float("inf"), float("inf")]])

    result = link_continuations([t1, t2, t3], {1: PAGE_HEIGHT, 2: PAGE_HEIGHT, 3: PAGE_HEIGHT}, {1: PAGE_WIDTH, 2: PAGE_WIDTH, 3: PAGE_WIDTH})

    assert len(result) == 3
    assert {tuple(t["pages"]) for t in result} == {(1,), (2,), (3,)}


def test_chains_three_consecutive_pages_into_one_table():
    t1 = _table("1:t:0", 1, bottom_y=970.0, headers=["Date", "Desc", "Amount"], column_bounds=COLS)
    t2 = _table("2:t:0", 2, bottom_y=970.0, headers=["", "", ""], column_bounds=COLS)
    t3 = _table("3:t:0", 3, bottom_y=400.0, headers=["", "", ""], column_bounds=COLS)

    result = link_continuations(
        [t1, t2, t3], {1: PAGE_HEIGHT, 2: PAGE_HEIGHT, 3: PAGE_HEIGHT}, {1: PAGE_WIDTH, 2: PAGE_WIDTH, 3: PAGE_WIDTH}
    )

    assert len(result) == 1
    assert result[0]["pages"] == [1, 2, 3]
    assert result[0]["row_count"] == 3


def test_standalone_table_still_gets_a_pages_field():
    t1 = _table("1:t:0", 1, bottom_y=300.0, headers=["A"], column_bounds=[[-float("inf"), float("inf")]])
    result = link_continuations([t1], {1: PAGE_HEIGHT}, {1: PAGE_WIDTH})
    assert result[0]["pages"] == [1]


def test_missing_page_dimensions_never_links_anything():
    """No real height/width data for a page -> never guess continuation
    from geometry we don't actually have."""
    earlier = _table("1:t:0", 1, bottom_y=970.0, headers=["Date", "Desc", "Amount"], column_bounds=COLS)
    later = _table("2:t:0", 2, bottom_y=400.0, headers=["", "", ""], column_bounds=COLS)

    result = link_continuations([earlier, later], {}, {})

    assert len(result) == 2
