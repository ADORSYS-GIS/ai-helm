#!/usr/bin/env python3
"""
Percentile / dimension-slicing analysis for gateway access logs pulled from
Loki (or any store that gives you a list of JSON log lines).

Usage:
    python3 loki_percentile_analysis.py /path/to/loki_result.json

Expects the standard Loki query_range JSON shape:
    { "data": { "result": [ { "stream": {...}, "values": [[ts, line], ...] }, ... ] } }

Adjust the FIELD_* constants below to match your access-log schema before running.
"""

import json
import sys
from collections import defaultdict

# --- Adjust these to your schema -------------------------------------------------
FIELD_TOTAL_DURATION_MS = "duration"                       # total client-observed duration
FIELD_UPSTREAM_TIME_MS = "x-envoy-upstream-service-time"   # upstream time-to-first-byte
FIELD_STATUS_DETAIL = "response_code_details"               # e.g. via_upstream / response_timeout
HAPPY_PATH_VALUE = "via_upstream"
FIELD_DIMENSION = "gen_ai.request.model"                    # e.g. model / route_name / backend
FIELD_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"           # optional, for LLM tok/s calc
FIELD_INPUT_TOKENS = "gen_ai.usage.input_tokens"             # optional
# -----------------------------------------------------------------------------------


def to_f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_rows(path):
    with open(path) as f:
        data = json.load(f)
    rows = []
    for stream in data.get("data", {}).get("result", []):
        for _ts, line in stream.get("values", []):
            try:
                rows.append(json.loads(line))
            except (json.JSONDecodeError, TypeError):
                continue
    return rows


def pctl(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    idx = min(int(len(vals) * p), len(vals) - 1)
    return vals[idx]


def print_stats(label, vals):
    if not vals:
        print(f"{label}: n=0 (no data)")
        return
    vals_sorted = sorted(vals)
    n = len(vals_sorted)
    print(
        f"{label}: n={n} p50={pctl(vals_sorted,.5):.0f} "
        f"p95={pctl(vals_sorted,.95):.0f} p99={pctl(vals_sorted,.99):.0f} "
        f"max={vals_sorted[-1]:.0f}"
    )


def main(path):
    rows = load_rows(path)
    print(f"Loaded {len(rows)} log lines\n")

    # Step 3: overall duration vs upstream-time split
    durations = [to_f(r.get(FIELD_TOTAL_DURATION_MS)) for r in rows]
    durations = [d for d in durations if d is not None]
    upstream = [to_f(r.get(FIELD_UPSTREAM_TIME_MS)) for r in rows]
    upstream = [u for u in upstream if u is not None]

    print("=== Overall: total duration vs upstream (TTFB) time ===")
    print_stats("duration", durations)
    print_stats("upstream_service_time", upstream)
    print()

    # Status/response classification breakdown
    status_counts = defaultdict(int)
    for r in rows:
        status_counts[r.get(FIELD_STATUS_DETAIL, "<missing>")] += 1
    print("=== response_code_details breakdown ===")
    for k, v in sorted(status_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    print()

    # Step 4: per-dimension duration percentiles (happy path only)
    by_dim = defaultdict(list)
    for r in rows:
        if r.get(FIELD_STATUS_DETAIL) != HAPPY_PATH_VALUE:
            continue
        d = to_f(r.get(FIELD_TOTAL_DURATION_MS))
        dim = r.get(FIELD_DIMENSION)
        if d is not None and dim:
            by_dim[dim].append(d)

    print(f"=== Per-{FIELD_DIMENSION} duration (happy path only) ===")
    for dim, vals in sorted(by_dim.items()):
        print_stats(dim, vals)
    print()

    # Optional: LLM effective tok/s per dimension
    by_dim_tps = defaultdict(list)
    for r in rows:
        if r.get(FIELD_STATUS_DETAIL) != HAPPY_PATH_VALUE:
            continue
        d = to_f(r.get(FIELD_TOTAL_DURATION_MS))
        o = to_f(r.get(FIELD_OUTPUT_TOKENS))
        dim = r.get(FIELD_DIMENSION)
        if d and o and o > 0 and dim:
            by_dim_tps[dim].append(o * 1000.0 / d)  # assumes duration in ms

    if any(by_dim_tps.values()):
        print(f"=== Per-{FIELD_DIMENSION} effective output tokens/sec (low = likely hidden reasoning tokens) ===")
        for dim, vals in sorted(by_dim_tps.items()):
            vals.sort()
            n = len(vals)
            print(f"  {dim}: n={n} median={vals[n//2]:.2f} min={vals[0]:.2f} max={vals[-1]:.2f}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <loki_result.json>")
        sys.exit(1)
    main(sys.argv[1])
