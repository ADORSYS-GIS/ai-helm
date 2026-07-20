#!/usr/bin/env node
/**
 * Qwen2.5-3B-AWQ LMCache A/B Comparison Report Generator
 *
 * Reads two Artillery JSON reports (baseline vs LMCache) for a given phase
 * and produces a Markdown comparison table + key findings.
 *
 * Usage:
 *   node generate-comparison.js \
 *     reports/report-qwen25-prefix-reuse-nolmcache.json \
 *     reports/report-qwen25-prefix-reuse-lmcache.json \
 *     "Prefix Reuse" \
 *     reports/comparison-prefix-reuse.md
 */

const fs = require('fs');

function extractMetrics(reportData) {
  const agg = reportData.aggregate || {};
  const counters = agg.counters || {};
  const summaries = agg.summaries || {};
  const rt = summaries['http.response_time'] || {};
  const total = counters['http.requests'] || 0;
  const ok = counters['http.codes.200'] || counters['http.codes.2xx'] || 0;
  const errors = counters['http.errors'] || 0;
  return {
    totalRequests: total,
    successful: ok,
    errors: errors,
    successRate: total > 0 ? (ok / total * 100).toFixed(2) : '0.00',
    minMs: rt.min,
    meanMs: rt.mean,
    p50Ms: rt.median,
    p75Ms: rt.p75,
    p90Ms: rt.p90,
    p95Ms: rt.p95,
    p99Ms: rt.p99,
    maxMs: rt.max,
  };
}

function fmtMs(v) {
  if (v === undefined || v === null) return 'N/A';
  return `${v.toFixed(1)} ms`;
}

function fmtPct(v) {
  return `${v}%`;
}

function delta(base, treat) {
  if (base === undefined || treat === undefined) return 'N/A';
  const d = treat - base;
  const pct = base !== 0 ? (d / base * 100).toFixed(1) : 'N/A';
  const sign = d >= 0 ? '+' : '';
  return `${sign}${d.toFixed(1)} ms (${sign}${pct}%)`;
}

function generateMarkdown(baseMetrics, treatMetrics, phaseName, outputFile) {
  const lines = [];
  lines.push(`# LMCache A/B Comparison: ${phaseName}\n`);
  lines.push(`Generated: ${new Date().toISOString()}\n`);
  lines.push(`## Metrics\n`);
  lines.push(`| Metric | Baseline (no LMCache) | Treatment (LMCache) | Delta |`);
  lines.push(`|---|---|---|---|`);
  lines.push(`| Total requests | ${baseMetrics.totalRequests} | ${treatMetrics.totalRequests} | |`);
  lines.push(`| Successful | ${baseMetrics.successful} | ${treatMetrics.successful} | |`);
  lines.push(`| Error count | ${baseMetrics.errors} | ${treatMetrics.errors} | |`);
  lines.push(`| Success rate | ${fmtPct(baseMetrics.successRate)} | ${fmtPct(treatMetrics.successRate)} | |`);
  lines.push(`| Min latency | ${fmtMs(baseMetrics.minMs)} | ${fmtMs(treatMetrics.minMs)} | |`);
  lines.push(`| Mean latency | ${fmtMs(baseMetrics.meanMs)} | ${fmtMs(treatMetrics.meanMs)} | ${delta(baseMetrics.meanMs, treatMetrics.meanMs)} |`);
  lines.push(`| **p50 (median)** | **${fmtMs(baseMetrics.p50Ms)}** | **${fmtMs(treatMetrics.p50Ms)}** | **${delta(baseMetrics.p50Ms, treatMetrics.p50Ms)}** |`);
  lines.push(`| p75 | ${fmtMs(baseMetrics.p75Ms)} | ${fmtMs(treatMetrics.p75Ms)} | ${delta(baseMetrics.p75Ms, treatMetrics.p75Ms)} |`);
  lines.push(`| p90 | ${fmtMs(baseMetrics.p90Ms)} | ${fmtMs(treatMetrics.p90Ms)} | ${delta(baseMetrics.p90Ms, treatMetrics.p90Ms)} |`);
  lines.push(`| **p95** | **${fmtMs(baseMetrics.p95Ms)}** | **${fmtMs(treatMetrics.p95Ms)}** | **${delta(baseMetrics.p95Ms, treatMetrics.p95Ms)}** |`);
  lines.push(`| p99 | ${fmtMs(baseMetrics.p99Ms)} | ${fmtMs(treatMetrics.p99Ms)} | ${delta(baseMetrics.p99Ms, treatMetrics.p99Ms)} |`);
  lines.push(`| Max latency | ${fmtMs(baseMetrics.maxMs)} | ${fmtMs(treatMetrics.maxMs)} | |`);
  lines.push(``);

  // Key findings
  lines.push(`## Key Findings\n`);
  const p50Improvement = baseMetrics.p50Ms && treatMetrics.p50Ms
    ? ((baseMetrics.p50Ms - treatMetrics.p50Ms) / baseMetrics.p50Ms * 100).toFixed(1)
    : null;
  const p95Improvement = baseMetrics.p95Ms && treatMetrics.p95Ms
    ? ((baseMetrics.p95Ms - treatMetrics.p95Ms) / baseMetrics.p95Ms * 100).toFixed(1)
    : null;

  if (p50Improvement !== null) {
    if (p50Improvement > 0) {
      lines.push(`- **p50 improved by ${p50Improvement}%** with LMCache (${fmtMs(baseMetrics.p50Ms)} → ${fmtMs(treatMetrics.p50Ms)}).`);
    } else {
      lines.push(`- **p50 regressed by ${Math.abs(p50Improvement)}%** with LMCache (${fmtMs(baseMetrics.p50Ms)} → ${fmtMs(treatMetrics.p50Ms)}).`);
    }
  }
  if (p95Improvement !== null) {
    if (p95Improvement > 0) {
      lines.push(`- **p95 improved by ${p95Improvement}%** with LMCache (${fmtMs(baseMetrics.p95Ms)} → ${fmtMs(treatMetrics.p95Ms)}).`);
    } else {
      lines.push(`- **p95 regressed by ${Math.abs(p95Improvement)}%** with LMCache (${fmtMs(baseMetrics.p95Ms)} → ${fmtMs(treatMetrics.p95Ms)}).`);
    }
  }
  if (phaseName.toLowerCase().includes('prefix')) {
    lines.push(`- **Phase**: prefix reuse — LMCache is expected to help here if the shared prefix is evicted from vLLM's GPU cache between requests.`);
  } else {
    lines.push(`- **Phase**: cold unique — LMCache is expected to add store overhead with no retrieval benefit (control phase).`);
  }
  lines.push(``);

  const md = lines.join('\n');
  if (outputFile) {
    fs.writeFileSync(outputFile, md);
    console.log(`Comparison report written to ${outputFile}`);
  }
  console.log(md);
}

// Main
const [,, baseFile, treatFile, phaseName, outputFile] = process.argv;
if (!baseFile || !treatFile) {
  console.log('Usage: node generate-comparison.js <baseline.json> <treatment.json> "Phase Name" [output.md]');
  process.exit(1);
}

const baseData = JSON.parse(fs.readFileSync(baseFile, 'utf8'));
const treatData = JSON.parse(fs.readFileSync(treatFile, 'utf8'));
const baseMetrics = extractMetrics(baseData);
const treatMetrics = extractMetrics(treatData);
generateMarkdown(baseMetrics, treatMetrics, phaseName || 'Comparison', outputFile);