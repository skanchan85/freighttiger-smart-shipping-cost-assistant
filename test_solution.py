from pathlib import Path
import pandas as pd
from freight_cost_assistant import build_output, note_for_route

HERE = Path(__file__).resolve().parent
output, weekly, notes = build_output(HERE / "shipment_records.csv", HERE / "context_notes.csv")

assert len(weekly) == 728, f"Expected 728 route-week aggregates, got {len(weekly)}"
assert list(output.columns) == [
    "route", "week_of", "cost_per_tonne_km", "vs_own_history",
    "vs_similar_routes", "flagged", "matched_note_id", "reason"
]

# Validate aggregation against the provided example values.
examples = [
    ("Delhi-Jaipur", "2024-11-11", 4.17),
    ("Ahmedabad-Mumbai", "2025-01-20", 3.29),
    ("Mumbai-Pune", "2025-09-15", 3.98),
]
for route, week, expected in examples:
    row = weekly[(weekly.route == route) & (weekly.week_of == pd.Timestamp(week))]
    assert len(row) == 1
    assert round(float(row.iloc[0].cost_per_tonne_km), 2) == expected

# Confirm the sample's supported note matches.
n002 = output[(output.route == "Ahmedabad-Mumbai") & (output.week_of == "2025-01-20")]
assert len(n002) == 1
assert n002.iloc[0].matched_note_id == "N002"
assert n002.iloc[0].flagged == "No (justified)"

# Unexplained rows must not carry a fabricated note ID.
unexplained = output[output.flagged == "Yes"]
assert (unexplained.matched_note_id == "").all()

# N003 is a nationwide 5-7% note, not proof for a route-specific anomaly.
n003_id, n003_reason = note_for_route(
    "Mumbai-Pune", pd.Timestamp("2025-05-05"), 6.0, notes
)
assert n003_id == "", "N003 must not justify a route-specific outlier."

print("All tests passed.")
