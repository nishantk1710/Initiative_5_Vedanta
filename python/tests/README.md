# Test harness

Regression safety net for the extraction pipeline. Added in Phase 0 of the
generic-document-extraction refactor, before any architectural change, so
"invoice/BOQ extraction did not regress" is a checkable claim rather than a
hope.

## Running

```bash
npm run test:py          # fast only (~26s) — the pre-commit signal
npm run test:py:slow     # real OCR pipeline (~20 min)
npm run test:py:all      # everything
```

Or directly: `.venv/Scripts/python.exe -m pytest`

`pytest.ini` sets `addopts = -m "not slow"`, so a bare `pytest` stays fast.

## Layout

| File | Speed | Covers |
|---|---|---|
| `test_validation_rules.py` | fast | confidence bands, required/optional fields, numeric parsing, arithmetic incl. tax-inclusive, row status, LLM review-flooring, marker leakage |
| `test_routing_and_regions.py` | fast | `is_meaningful_text` junk-layer rejection, region keep/drop, the line_item-XOR-metadata invariant, document classification |
| `test_line_items_geometry.py` | fast | header-text column mapping, numeric coercion, optional-column omission, no-header and one-header tables, per-field provenance, page isolation |
| `test_llm_contract.py` | fast | malformed-response degradation, no-hallucination drops, provenance tagging, bbox recovery, prompt format-agnosticism |
| `test_pipeline_golden.py` | **slow** | real routing, golden values on bundled samples, arbitrary-document robustness, bbox bounds, artifact files |

## Fixtures

`conftest.py` generates documents deterministically (PyMuPDF + PIL) rather
than committing binaries, so each fixture's exact content is visible in code.
Covers digital/scanned/mixed PDFs, image input, junk text layers, bordered and
borderless tables, a non-English table, a non-line-item table (bank
statement), prose documents (resume/contract/unknown), multi-page
continuation, multi-column, and tables with zero or one recognisable header.

Real-world documents that can't be synthesised (the photographed Walkway
receipt) stay under `uploads/` and are referenced by id.

The `run_pipeline` fixture deletes each `results/<id>/` directory afterwards —
slow runs leave nothing behind.

## Markers

- `slow` — runs genuine layout detection + OCR. Excluded by default.
- `llm` — needs live Azure credentials in `.env`; skipped when unconfigured.

## Known-gap tests (`xfail`, `strict=True`)

Two tests encode intended behaviour that does not exist yet. They fail today
by design and will flip to passing when the relevant phase lands — `strict`
means they'll also fail loudly if they start passing without the work being
done deliberately.

| Test | Blocks on |
|---|---|
| `test_mismatch_is_not_blindly_attributed_to_amount` | Phase 4 — safe correction protocol. `arithmetic_mismatch` is currently pinned on `amount` regardless of which field is actually suspect, so a misread quantity gets "fixed" by corrupting a correct amount. Reproduced live on `sow-3`. |
| `test_non_invoice_boq_document_types_are_representable` | Phase 3 — open document-type vocabulary. `classify_document` returns a bare string from a closed set, so a bank statement can only ever come back `unknown`. |

## Bugs this harness found immediately

Both were real defects in shipped code, not bad tests:

1. **Unreachable `incomplete` branch** (`line_items.py`) — `_detect_header_row`
   was called with `min_matched=2`, so the matched count could only be 0 or
   ≥2, never exactly 1. The "found a table but couldn't map its columns"
   path was dead code, which is why every run reported `incomplete_rows: 0`.
   Fixed with a two-pass search (strongest header first, so a well-formed
   header still wins over a stray earlier keyword row).

2. **Short exact matches jumping across the page** (`llm_line_items.py`) —
   exact bbox matches were deliberately not distance-gated on the reasoning
   that exact equality is self-evidencing. True for `16-98716-C-45-FOOTWEAR`,
   false for `"1"`, which exact-matches a page number as readily as the real
   cell. Now only matches of ≥5 characters skip the distance gate.
