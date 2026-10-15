# FreightTiger Smart Shipping Cost Assistant

## Overview
This project analyzes shipment records week by week, calculates cost per tonne-kilometre, compares each route with its own recent history and same-week routes of the same `route_type`, and outputs unusual increases for human review.

This is a **deterministic baseline implementation**. It does not call an external LLM or use a vector database yet. Notes are matched using explicit route/date rules so that explanations are auditable and repeatable. This avoids inventing reasons when a note does not support a specific route and time.

## Files
- `freight_cost_assistant.py` — implementation
- `shipment_records.csv` — input shipment records
- `context_notes.csv` — contextual notes
- `sample_output_format_v2.csv` — provided output example/column contract
- `output.csv` — generated anomaly rows
- `test_solution.py` — lightweight correctness checks
- `reproducibility_check.txt` — hashes from three runs
- `token_cost_log.txt` — LLM token/cost log for this baseline

## Requirements
- Python 3.10+
- pandas

Install:
```bash
python -m pip install pandas
```

## Run
From this folder:
```bash
python freight_cost_assistant.py --shipments shipment_records.csv --notes context_notes.csv --output output.csv
```

Run checks:
```bash
python test_solution.py
```

## Method
1. Build route names as `origin-destination`.
2. Convert each shipment date to the Monday of its Monday-Sunday week.
3. Aggregate each route/week: sum freight cost and sum `quantity_tonnes * distance_km`.
4. Calculate weekly cost per tonne-km as `sum(freight_cost_inr) / sum(quantity_tonnes * distance_km)`.
5. Compare with the average cost from up to the previous 8 **observed route-weeks**, strictly before the current week. No current-week data is included in its own baseline. Where fewer prior weeks exist, all available prior route-weeks are used.
6. Compare with the average of other routes in the same week and same `route_type`, excluding the route itself.
7. Emit a row when the increase is at least **10% vs own history OR 15% vs same-type peers**. The case brief does not prescribe numeric thresholds, so these are explicit, configurable starting thresholds rather than thresholds supplied by FreightTiger.
8. A row is `No (justified)` only if an applicable note supports that route and time. Otherwise it is `Yes` and asks for human review. Notes saying costs were unaffected, demand was stable, or road conditions improved are not treated as reasons for a cost rise.

## Note matching safeguards
- `N001` is used only for Chennai-Bangalore weeks starting 2025-02-24 and 2025-03-03, which overlap the stated flooding period.
- `N002` is used only for Ahmedabad-Mumbai week starting 2025-01-20.
- `N003` is not accepted as a justification for a route-level anomaly. It describes a nationwide 5-7% diesel-price rise, which cannot explain a much larger route-specific deviation from same-week peer routes. For the week starting 2025-05-05, it may be mentioned as context but `matched_note_id` remains blank unless a route-specific note supports the anomaly.
- Other notes are not treated as positive explanations because they do not establish a cost increase for the matching route and time. In particular, general notes about stable demand, unaffected costs, improved roads, or nationwide changes do not automatically justify an outlier.
- A matched note ID is included in `matched_note_id`; it is blank when no supporting note was found.

## Important limitations / next improvements
- This first version uses deterministic note matching, not semantic/vector retrieval or an LLM. That is deliberate for an auditable first baseline, but the AI/RAG bonus is not yet implemented.
- The case brief does not define the anomaly thresholds. The 10% and 15% thresholds should be discussed and justified in the walkthrough and can be tuned after evaluation.
- The history baseline uses the last eight prior route-weeks that have shipment data. Weeks with no shipments have no weekly cost and are not fabricated or filled in.
- `sample_output_format_v2.csv` contains unescaped commas in one example reason, so some CSV parsers reject its sample rows. The output uses the eight columns from its header and writes valid CSV quoting.

## Suggested 10-minute walkthrough
1. Explain the input files and route/week grouping.
2. Demonstrate the weighted cost-per-tonne-km formula.
3. Show own-history and peer comparisons.
4. Show one justified example (`N002` or `N001`) and one unexplained flag.
5. Explain why unsupported notes are not used as evidence.
6. Show the three-run reproducibility check and the no-LLM cost log.
7. Discuss thresholds and the next step: adding retrieval/RAG with citations to exact notes.
