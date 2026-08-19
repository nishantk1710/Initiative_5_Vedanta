from rules import evaluate_field, evaluate_arithmetic, combine_status

FIELD_NAMES = ("description", "quantity", "unit", "rate", "amount")


def run_validation(boq_rows: list[dict]) -> list[dict]:
    """Apply rules.py to every field in every row, tag each row with an
    overall status (worst-case across its fields), and record which rule(s)
    triggered — per field and aggregated at the row level."""
    for row in boq_rows:
        row_status = "valid"
        row_rules: list[str] = []

        for field_name in FIELD_NAMES:
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

    return boq_rows
