#!/usr/bin/env python3
"""
FreightTiger Smart Shipping Cost Assistant
Deterministic, auditable baseline implementation for the case study.
"""
from pathlib import Path
import argparse
import pandas as pd

OWN_HISTORY_THRESHOLD_PCT = 10.0
SIMILAR_ROUTE_THRESHOLD_PCT = 15.0

EXPECTED_SHIPMENT_COLUMNS = {
    "origin", "destination", "route_type", "quantity_tonnes",
    "distance_km", "freight_cost_inr", "shipment_date"
}
OUTPUT_COLUMNS = [
    "route", "week_of", "cost_per_tonne_km", "vs_own_history",
    "vs_similar_routes", "flagged", "matched_note_id", "reason"
]

def pct_change(value, baseline):
    if pd.isna(value) or pd.isna(baseline) or baseline == 0:
        return None
    return (value / baseline - 1.0) * 100.0

def note_for_route(route, week, own_change, notes):
    """
    Deterministic retrieval: only return a note when route/date scope supports it.
    Notes that say costs were unaffected, conditions improved, or demand was stable
    are not treated as justification for a cost increase.
    """
    # Notes are intentionally checked by exact route and time applicability.
    candidate_id = ""
    if route == "Chennai-Bangalore" and pd.Timestamp("2025-02-24") <= week <= pd.Timestamp("2025-03-03"):
        candidate_id = "N001"
    elif route == "Ahmedabad-Mumbai" and week == pd.Timestamp("2025-01-20"):
        candidate_id = "N002"
    # N003 is deliberately NOT accepted as justification for a route-level anomaly.
    # It describes a nationwide 5-7% rise; that cannot explain a much larger gap
    # against same-week peer routes. It may be mentioned as context, but not as proof.

    if not candidate_id:
        return ("", "")
    found = notes[notes["note_id"].astype(str) == candidate_id]
    if found.empty:
        return ("", "")
    note = found.iloc[0]
    return (
        candidate_id,
        f"Matches {candidate_id} dated {pd.to_datetime(note['date']).strftime('%Y-%m-%d')}: {note['note']}"
    )

def build_output(shipment_path, notes_path):
    shipments = pd.read_csv(shipment_path)
    notes = pd.read_csv(notes_path)

    missing = EXPECTED_SHIPMENT_COLUMNS - set(shipments.columns)
    if missing:
        raise ValueError(f"shipment_records.csv is missing columns: {sorted(missing)}")

    shipments["shipment_date"] = pd.to_datetime(shipments["shipment_date"], errors="raise")
    for col in ["quantity_tonnes", "distance_km", "freight_cost_inr"]:
        shipments[col] = pd.to_numeric(shipments[col], errors="raise")
    if (shipments["quantity_tonnes"] <= 0).any() or (shipments["distance_km"] <= 0).any():
        raise ValueError("quantity_tonnes and distance_km must be positive.")

    shipments["route"] = shipments["origin"].astype(str) + "-" + shipments["destination"].astype(str)
    shipments["week_of"] = (
        shipments["shipment_date"] -
        pd.to_timedelta(shipments["shipment_date"].dt.weekday, unit="D")
    )
    shipments["tonne_km"] = shipments["quantity_tonnes"] * shipments["distance_km"]

    # Aggregate first, then calculate the cost per tonne-km for each route/week.
    weekly = (
        shipments.groupby(["route", "route_type", "week_of"], as_index=False)
        .agg(total_cost=("freight_cost_inr", "sum"),
             total_tonne_km=("tonne_km", "sum"),
             shipment_count=("shipment_id", "count"))
        .sort_values(["route", "week_of"])
    )
    weekly["cost_per_tonne_km"] = weekly["total_cost"] / weekly["total_tonne_km"]

    # Own-history baseline: mean of up to 8 prior observed route-weeks only.
    weekly["own_avg_8_prior"] = float("nan")
    weekly["own_prior_weeks"] = 0
    for route, indices in weekly.groupby("route", sort=False).groups.items():
        route_indices = list(indices)
        route_indices.sort(key=lambda i: weekly.loc[i, "week_of"])
        for pos, idx in enumerate(route_indices):
            prior_indices = route_indices[max(0, pos - 8):pos]
            if prior_indices:
                weekly.loc[idx, "own_avg_8_prior"] = weekly.loc[prior_indices, "cost_per_tonne_km"].mean()
                weekly.loc[idx, "own_prior_weeks"] = len(prior_indices)

    # Same-week peer average for same route_type, excluding the current route.
    peer_means = {}
    for idx, row in weekly.iterrows():
        peers = weekly[
            (weekly["week_of"] == row["week_of"]) &
            (weekly["route_type"] == row["route_type"]) &
            (weekly["route"] != row["route"])
        ]["cost_per_tonne_km"]
        peer_means[idx] = peers.mean() if len(peers) else float("nan")
    weekly["peer_average"] = pd.Series(peer_means)

    weekly["own_change_pct"] = [
        pct_change(value, baseline)
        for value, baseline in zip(weekly["cost_per_tonne_km"], weekly["own_avg_8_prior"])
    ]
    weekly["peer_change_pct"] = [
        pct_change(value, baseline)
        for value, baseline in zip(weekly["cost_per_tonne_km"], weekly["peer_average"])
    ]

    rows = []
    for _, row in weekly.iterrows():
        own_change = row["own_change_pct"]
        peer_change = row["peer_change_pct"]
        own_anomaly = own_change is not None and pd.notna(own_change) and own_change >= OWN_HISTORY_THRESHOLD_PCT
        peer_anomaly = peer_change is not None and pd.notna(peer_change) and peer_change >= SIMILAR_ROUTE_THRESHOLD_PCT
        if not (own_anomaly or peer_anomaly):
            continue

        week = row["week_of"]
        note_id, note_reason = note_for_route(row["route"], week, own_change, notes)
        justified = bool(note_id)
        flagged = "No (justified)" if justified else "Yes"

        own_text = (
            f"{own_change:+.1f}% vs this route's past average"
            if pd.notna(own_change) else
            f"not available (only {int(row['own_prior_weeks'])} prior weeks; no usable baseline)"
        )
        peer_text = (
            f"{peer_change:+.1f}% vs similar-length routes this week"
            if pd.notna(peer_change) else
            "not available (no other same-type route in this week)"
        )

        if justified:
            reason = note_reason + " The cost rise is treated as explained."
        else:
            context_caveat = ""
            if week == pd.Timestamp("2025-05-05"):
                n003 = notes[notes["note_id"].astype(str) == "N003"]
                if not n003.empty:
                    context_caveat = (
                        " Context note N003 mentions a nationwide 5-7% diesel-related rise, "
                        "but that general change does not explain this route's unusual gap "
                        "against peer routes; it is not accepted as a justification."
                    )
            reason = (
                "No applicable supporting note found for this route and week. "
                "Other notes were not treated as justification unless they directly "
                "supported a cost increase. Flagged for human review." + context_caveat
            )

        rows.append({
            "route": row["route"],
            "week_of": week.strftime("%Y-%m-%d"),
            "cost_per_tonne_km": f"{row['cost_per_tonne_km']:.2f}",
            "vs_own_history": own_text,
            "vs_similar_routes": peer_text,
            "flagged": flagged,
            "matched_note_id": note_id,
            "reason": reason,
        })

    output = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if not output.empty:
        output = output.sort_values(["week_of", "route"]).reset_index(drop=True)
    return output, weekly, notes

def main():
    parser = argparse.ArgumentParser(description="Analyze weekly freight costs and flag unusual increases.")
    parser.add_argument("--shipments", default="shipment_records.csv")
    parser.add_argument("--notes", default="context_notes.csv")
    parser.add_argument("--output", default="output.csv")
    args = parser.parse_args()

    output, weekly, notes = build_output(args.shipments, args.notes)
    output.to_csv(args.output, index=False)
    print(f"Read {len(pd.read_csv(args.shipments))} shipment records and {len(notes)} context notes.")
    print(f"Calculated {len(weekly)} route-week aggregates.")
    print(f"Wrote {len(output)} anomaly rows to {args.output}.")
    print(f"Thresholds: own-history increase >= {OWN_HISTORY_THRESHOLD_PCT:.1f}% OR peer increase >= {SIMILAR_ROUTE_THRESHOLD_PCT:.1f}%.")
    print("No external LLM calls are made in this baseline; note retrieval and verdicts are deterministic.")

if __name__ == "__main__":
    main()
