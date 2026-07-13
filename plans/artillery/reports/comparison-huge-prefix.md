# LMCache A/B Comparison: Huge Prefix (~9.7K tokens) — Eviction mix with Enhanced LMCache

Generated: 2026-07-10T14:01:16.072Z

## Metrics

| Metric | Baseline (no LMCache) | Treatment (LMCache) | Delta |
|---|---|---|---|
| Total requests | 250 | 250 | |
| Successful | 250 | 250 | |
| Error count | 0 | 0 | |
| Success rate | 100.00% | 100.00% | |
| Min latency | 132.0 ms | 120.0 ms | |
| Mean latency | 4660.1 ms | 665.3 ms | -3994.8 ms (-85.7%) |
| **p50 (median)** | **4147.4 ms** | **210.6 ms** | **-3936.8 ms (-94.9%)** |
| p75 | 5711.5 ms | 788.5 ms | -4923.0 ms (-86.2%) |
| p90 | 10407.3 ms | 1022.7 ms | -9384.6 ms (-90.2%) |
| **p95** | **11501.8 ms** | **2101.1 ms** | **-9400.7 ms (-81.7%)** |
| p99 | 12711.5 ms | 5272.4 ms | -7439.1 ms (-58.5%) |
| Max latency | 15623.0 ms | 7987.0 ms | |

## Key Findings

- **p50 improved by 94.9%** with LMCache (4147.4 ms → 210.6 ms).
- **p95 improved by 81.7%** with LMCache (11501.8 ms → 2101.1 ms).
- **Phase**: prefix reuse — LMCache is expected to help here if the shared prefix is evicted from vLLM's GPU cache between requests.
