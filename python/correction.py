"""Safe correction protocol for arithmetic-mismatch rows.

Only reached for a row validator.py already flagged with arithmetic_mismatch
on some field. Where the old flow sent just the single suspected field and
blindly accepted whatever came back, this sends the FULL correlated context —
quantity, rate, amount, taxAmount if present, each with its OWN confidence
and source, plus description/unit for grounding — and treats the model's
answer as a PROPOSAL, never a direct mutation. A deterministic gate decides
whether it's safe to apply; the model has no way to force a value through.

This is what actually prevents "amount was correct, quantity was misread,
but validator blamed amount, so the model corrupted amount to satisfy the
equation" — rules.py's evaluate_arithmetic already stopped blaming the wrong
field by default (see its docstring), but a hard mistake in either the
deterministic guess or the model's own reasoning could still slip through
without an independent, deterministic acceptance check on top. That check
lives here, not in the prompt.
"""

import json

from llm_client import post_chat_json
from rules import CONFIDENCE_ACCEPT_THRESHOLD, evaluate_arithmetic, parse_numeric

CORRELATED_FIELDS = ("quantity", "rate", "amount", "taxAmount")
CONTEXT_FIELDS = ("description", "unit")

_SYSTEM_PROMPT = (
    "You are checking one row of a structured table for an arithmetic "
    "inconsistency: amount should approximately equal quantity multiplied by "
    "rate (plus tax amount, if present). You are given each numeric field's "
    "OCR-read value, its own confidence score, and its source engine.\n\n"
    "Exactly one of these fields is usually the misread one. Decide which "
    "field is most likely wrong based on which value looks implausible AND "
    "has comparatively low confidence — do not suspect a field just because "
    "it happens to be the one the equation fails on; a field can be the "
    "reason the equation fails without being the wrong one.\n\n"
    "Return ONLY strict JSON, no prose, no markdown fencing:\n"
    '{"suspected_field": "quantity"|"rate"|"amount"|"taxAmount", '
    '"original_value": "...", "proposed_value": "...", "reason": "...", '
    '"confidence": 0.0}\n\n'
    "If you cannot confidently identify which field is wrong, or a "
    "correction is not obvious, return exactly "
    '{"suspected_field": null, "action": "no_safe_correction"} instead. '
    "Never propose changing a field whose own confidence is already high — "
    "a high-confidence read is more likely correct than the arithmetic "
    "check questioning it."
)


def _build_payload(row: dict) -> dict:
    payload: dict = {"context": {}, "fields": {}}
    for name in CONTEXT_FIELDS:
        if name in row:
            payload["context"][name] = row[name]["value"]
    for name in CORRELATED_FIELDS:
        if name in row:
            f = row[name]
            payload["fields"][name] = {
                "value": f["value"],
                "confidence": f.get("confidence", 0.0),
                "source": f.get("source"),
            }
    return payload


def propose_correction(row: dict) -> dict | None:
    """Ask the model which correlated field is likely wrong and what it
    should be. Returns the parsed proposal dict, or None on any failure,
    malformed response, or an explicit no_safe_correction — all treated
    identically by the caller: leave the row as it is."""
    payload = _build_payload(row)
    parsed = post_chat_json(_SYSTEM_PROMPT, json.dumps(payload), log_prefix="correction")

    if not isinstance(parsed, dict):
        return None

    field_name = parsed.get("suspected_field")
    if field_name is None:
        return None  # explicit no_safe_correction, or the model declined

    if field_name not in CORRELATED_FIELDS or field_name not in row:
        print(f"[correction] model named an unusable field: {field_name!r}")
        return None

    if "proposed_value" not in parsed:
        print(f"[correction] response missing proposed_value: {parsed!r}")
        return None

    return parsed


def apply_if_safe(row: dict, proposal: dict) -> bool:
    """Mutate row[field] in place IFF every safety check passes. Returns
    True if applied, False if the row was left untouched — a rejection here
    is a normal, expected outcome, not an error."""
    field_name = proposal["suspected_field"]
    field = row[field_name]

    # The one rule that can never be overridden: a field the engine itself
    # was already confident about is more trustworthy than a model's guess
    # that it's wrong. This is the direct fix for the corruption case —
    # amount sat at 0.99 confidence and would be rejected here outright,
    # regardless of what any proposal claims about it.
    if field.get("confidence", 0.0) >= CONFIDENCE_ACCEPT_THRESHOLD:
        print(
            f"[correction] rejected: {field_name} already has confidence "
            f"{field['confidence']:.2f} >= accept threshold — not overwriting it"
        )
        return False

    new_value = parse_numeric(proposal.get("proposed_value"))
    if new_value is None:
        print(f"[correction] rejected: proposed_value not numeric: {proposal.get('proposed_value')!r}")
        return False

    try:
        proposal_confidence = float(proposal.get("confidence", 0.0))
    except (TypeError, ValueError):
        proposal_confidence = 0.0

    # Simulate the correction and require that it actually resolves the
    # mismatch — a correction that doesn't fix anything is not worth the
    # data-integrity risk of mutating a value at all.
    trial_row = dict(row)
    trial_row[field_name] = dict(field, value=new_value)
    result = evaluate_arithmetic(trial_row)
    if result is None or result[0] != "valid":
        print(f"[correction] rejected: proposed {field_name}={new_value} does not resolve the mismatch")
        return False

    field["value"] = new_value
    # Never let a correction claim accept-level trust on its own say-so —
    # it is still an inferred value, not a direct read.
    field["confidence"] = min(proposal_confidence, CONFIDENCE_ACCEPT_THRESHOLD - 0.01)
    field["source"] = "llm"
    field["status"] = "review"  # corrected, not silently valid — mirrors llm_line_items.py's floor
    field["rules_triggered"] = [r for r in field.get("rules_triggered", []) if r != "arithmetic_mismatch"]
    field["rules_triggered"].append("llm_corrected")
    return True
