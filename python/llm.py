"""Azure AI Foundry calls for ambiguous-field normalization only.

Deliberately the LAST resort: only fields rules.py/validator.py tagged
'ambiguous' ever reach here, and only the minimal per-field payload is sent —
never the full document or unrelated rows. Endpoint/key/model come from env
vars only; never hardcode them, never expose via NEXT_PUBLIC_*.
"""

import json
import os
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

AZURE_FOUNDRY_ENDPOINT = os.environ.get("AZURE_FOUNDRY_ENDPOINT", "")
AZURE_FOUNDRY_API_KEY = os.environ.get("AZURE_FOUNDRY_API_KEY", "")
AZURE_FOUNDRY_MODEL = os.environ.get("AZURE_FOUNDRY_MODEL", "")

REQUEST_TIMEOUT_SECONDS = 20

_SYSTEM_PROMPT = (
    "You are normalizing a single ambiguous field extracted from a scanned "
    "mining bill-of-quantities document. Given the OCR value, its source "
    "engine, minimal row context, and why it failed validation, return ONLY "
    'strict JSON of the shape {"field": "...", "normalized_value": "...", '
    '"confidence": 0.0} with no extra text, no markdown fencing.'
)

FIELD_NAMES = ("description", "quantity", "unit", "rate", "amount")


def _call_azure_foundry(payload: dict) -> dict | None:
    """POST the minimal ambiguous-field payload to Azure Foundry and return
    the parsed {field, normalized_value, confidence} response, or None on
    any failure/malformed response. Never raises — a failed normalization
    just leaves the field ambiguous rather than crashing the pipeline."""
    if not (AZURE_FOUNDRY_ENDPOINT and AZURE_FOUNDRY_API_KEY and AZURE_FOUNDRY_MODEL):
        print("[llm] Azure Foundry not configured (missing endpoint/key/model) — leaving field ambiguous")
        return None

    body = json.dumps(
        {
            "model": AZURE_FOUNDRY_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
            "temperature": 0,
        }
    ).encode("utf-8")

    req = urllib_request.Request(
        AZURE_FOUNDRY_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json", "api-key": AZURE_FOUNDRY_API_KEY},
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            envelope = json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError) as exc:
        print(f"[llm] Azure Foundry request failed: {exc}")
        return None
    except json.JSONDecodeError as exc:
        print(f"[llm] Azure Foundry returned an invalid JSON envelope: {exc}")
        return None

    try:
        content = envelope["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        print(f"[llm] Azure Foundry response missing expected shape: {exc}")
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
        for field_name in FIELD_NAMES:
            field = row[field_name]
            if field.get("status") != "ambiguous":
                continue

            payload = {
                "field": field_name,
                "ocr_value": field["value"],
                "source": field["source"],
                "context": {
                    "description": row["description"]["value"],
                    "quantity": row["quantity"]["value"],
                    "unit": row["unit"]["value"],
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

    # re-derive each row's overall status from its (possibly just-updated) fields
    for row in validated_rows:
        statuses = [row[name]["status"] for name in FIELD_NAMES]
        if "ambiguous" in statuses:
            row["status"] = "ambiguous"
        elif "review" in statuses:
            row["status"] = "review"
        else:
            row["status"] = "valid"

    return validated_rows, llm_normalized_fields
