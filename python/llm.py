"""Azure AI Foundry calls for ambiguous-field normalization only.

Deliberately the LAST resort: only fields rules.py/validator.py tagged
'ambiguous' ever reach here, and only the minimal per-field payload is sent —
never the full document or unrelated rows. Endpoint/key/model come from env
vars only; never hardcode them, never expose via NEXT_PUBLIC_*.
"""

import json

from llm_client import post_chat_json
import correction

_SYSTEM_PROMPT = (
    "You are normalizing a single ambiguous field extracted from a scanned "
    "mining bill-of-quantities document. Given the OCR value, its source "
    "engine, minimal row context, and why it failed validation, return ONLY "
    'strict JSON of the shape {"field": "...", "normalized_value": "...", '
    '"confidence": 0.0} with no extra text, no markdown fencing.'
)

_FIELD_KEYS = ("description", "quantity", "unit", "rate", "amount", "itemCode", "taxRate", "taxAmount")
CORRELATED_ARITHMETIC_FIELDS = ("quantity", "rate", "amount", "taxAmount")


def _row_field_names(row: dict) -> list[str]:
    return [name for name in _FIELD_KEYS if name in row]


def _call_azure_foundry(payload: dict) -> dict | None:
    """POST the minimal ambiguous-field payload to Azure Foundry and return
    the parsed {field, normalized_value, confidence} response, or None on
    any failure/malformed response. Never raises — a failed normalization
    just leaves the field ambiguous rather than crashing the pipeline."""
    parsed = post_chat_json(_SYSTEM_PROMPT, json.dumps(payload), log_prefix="llm")
    if parsed is None:
        return None

    if not isinstance(parsed, dict) or not {"field", "normalized_value", "confidence"} <= parsed.keys():
        print(f"[llm] Azure Foundry response missing required keys: {parsed!r}")
        return None

    try:
        parsed["confidence"] = float(parsed["confidence"])
    except (TypeError, ValueError):
        print(f"[llm] Azure Foundry confidence not numeric: {parsed!r}")
        return None

    return parsed


def normalize_ambiguous(validated_rows: list[dict]) -> tuple[list[dict], int]:
    """For every field tagged 'ambiguous', call Azure Foundry with only its
    minimal context. On a well-formed success, update the field's value and
    bump its row toward 'review' (never silently 'valid' — a human still
    confirms an LLM-normalized field). Returns (rows, llm_normalized_fields)."""
    llm_normalized_fields = 0

    for row in validated_rows:
        if row.get("status") == "incomplete":
            continue  # nothing structured to normalize — column mapping itself failed

        # Arithmetic mismatches go through the safe-correction protocol
        # FIRST, once per row, with the full correlated context — not the
        # single-field flow below. That flow sending only "here's a value,
        # fix it" is exactly what let a misread quantity get "fixed" by
        # corrupting a correct amount: the model only ever saw the one
        # field validator.py happened to flag, with no way to know a
        # different field was actually the problem.
        has_arithmetic_issue = any(
            "arithmetic_mismatch" in row[name].get("rules_triggered", [])
            for name in _row_field_names(row)
            if name in CORRELATED_ARITHMETIC_FIELDS
        )
        if has_arithmetic_issue:
            proposal = correction.propose_correction(row)
            if proposal is not None and correction.apply_if_safe(row, proposal):
                llm_normalized_fields += 1

        for field_name in _row_field_names(row):
            field = row[field_name]
            if field.get("status") != "ambiguous":
                continue
            if field.get("source") == "llm":
                # already produced by llm_line_items.py — asking the same
                # model to normalize its own output is circular, so leave it
                continue
            if not str(field.get("value", "")).strip():
                # required field missing entirely (rules.py:required_field_missing)
                # — there is no OCR value to correct, only re-extraction could
                # fix this, so leave it ambiguous rather than send an empty
                # payload to the LLM
                continue

            payload = {
                "field": field_name,
                "ocr_value": field["value"],
                "source": field["source"],
                "context": {
                    "description": row["description"]["value"],
                    "quantity": row["quantity"]["value"],
                    "unit": row["unit"]["value"] if "unit" in row else None,
                },
                "validation_error": field.get("rules_triggered", []),
            }

            result = _call_azure_foundry(payload)
            if result is None:
                continue  # leave field ambiguous rather than guess

            field["value"] = str(result["normalized_value"])
            field["confidence"] = result["confidence"]
            field["status"] = "review"  # LLM-normalized — still needs human confirmation
            field["rules_triggered"] = field.get("rules_triggered", []) + ["llm_normalized"]
            llm_normalized_fields += 1

    # re-derive each row's overall status from its (possibly just-updated)
    # fields — except "incomplete" rows, which never went through per-field
    # evaluation and must keep that status rather than be recomputed as if
    # they had normal field statuses to aggregate.
    for row in validated_rows:
        if row.get("status") == "incomplete":
            continue
        field_names = _row_field_names(row)
        statuses = [row[name]["status"] for name in field_names]
        if "ambiguous" in statuses:
            row["status"] = "ambiguous"
        elif "review" in statuses:
            row["status"] = "review"
        else:
            row["status"] = "valid"

        # A row whose structure came from the LLM never re-derives to
        # "valid" — validator.py floored it at "review" and that floor must
        # survive this recomputation, independent of how the individual
        # field confidences happen to band.
        if row["status"] == "valid" and any(row[name].get("source") == "llm" for name in field_names):
            row["status"] = "review"

    return validated_rows, llm_normalized_fields
