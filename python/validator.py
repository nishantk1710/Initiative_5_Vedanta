from rules import evaluate_field, evaluate_arithmetic, combine_status

# LineItem field keys that carry an ExtractedValue (everything else on a row
# dict is a status/marker key, not a field to validate).
_FIELD_KEYS = ("description", "quantity", "unit", "rate", "amount", "itemCode", "taxRate", "taxAmount")


def _row_field_names(row: dict) -> list[str]:
    """Only the fields actually present on this row — optional columns
    (unit/itemCode/taxRate/taxAmount) may be entirely absent, per LineItem."""
    return [name for name in _FIELD_KEYS if name in row]


def run_validation(line_items: list[dict]) -> list[dict]:
    """Apply rules.py to every field present on every row, tag each row with
    an overall status (worst-case across its fields), and record which
    rule(s) triggered — per field and aggregated at the row level.

    A row line_items.py already tagged "_status_override": "incomplete"
    (a table-shaped region whose header couldn't be confidently mapped to
    known columns) bypasses field-by-field evaluation entirely — there's
    nothing meaningful to validate when we didn't attempt column
    assignment in the first place.
    """
    for row in line_items:
        if row.pop("_status_override", None) == "incomplete":
            row["status"] = "incomplete"
            row["rules_triggered"] = ["table_header_not_identified"]
            for field_name in _row_field_names(row):
                row[field_name]["status"] = "incomplete"
                row[field_name]["rules_triggered"] = []
            continue

        row_status = "valid"
        row_rules: list[str] = []

        for field_name in _row_field_names(row):
            field = row[field_name]
            status, rules_triggered = evaluate_field(field_name, field)
            field["status"] = status
            field["rules_triggered"] = rules_triggered
            row_status = combine_status(row_status, status)
            row_rules.extend(f"{field_name}:{rule}" for rule in rules_triggered)

        arithmetic_result = evaluate_arithmetic(row)
        if arithmetic_result is not None:
            arithmetic_status, arithmetic_rules = arithmetic_result
            if arithmetic_rules:
                row["amount"]["status"] = combine_status(row["amount"]["status"], arithmetic_status)
                row["amount"]["rules_triggered"] = row["amount"]["rules_triggered"] + arithmetic_rules
                row_status = combine_status(row_status, arithmetic_status)
                row_rules.extend(f"amount:{rule}" for rule in arithmetic_rules)

        row["status"] = row_status
        row["rules_triggered"] = row_rules

    return line_items
