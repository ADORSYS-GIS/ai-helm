#!/usr/bin/env node
/**
 * Artillery Report Generator
 * Generates HTML reports from Artillery JSON output
 * 
 * Usage: node generate-report.js <report.json> [output.html]
 */

const fs = require('fs');
const path = require('path');

// ANSI color codes for terminal output
const colors = {
  reset: '\x1b[0m',
  bright: '\x1b[1m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  cyan: '\x1b[36m',
  dim: '\x1b[2m'
};

function formatNumber(num) {
  if (num === undefined || num === null) return 'N/A';
  return num.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

function formatMs(ms) {
  if (ms === undefined || ms === null) return 'N/A';
  return `${formatNumber(ms)} ms`;
}

function getPercentile(summary, percentile) {
  if (!summary) return null;
  return summary[percentile];
}

function getStatusColor(rate) {
  if (rate >= 99.9) return '#22c55e';
  if (rate >= 99) return '#eab308';
  if (rate >= 95) return '#f97316';
  return '#ef4444';
}

function getLatencyColor(p95, thresholds = { good: 500, warning: 1000 }) {
  if (p95 <= thresholds.good) return '#22c55e';
  if (p95 <= thresholds.warning) return '#eab308';
  return '#ef4444';
}

function generateHTML(reportData, reportName) {
  const aggregate = reportData.aggregate || {};
  const counters = aggregate.counters || {};
  const summaries = aggregate.summaries || {};
  const intermediate = reportData.intermediate || [];

  // Calculate key metrics
  const totalRequests = counters['http.requests'] || 0;
  const successfulRequests = counters['http.codes.200'] || counters['http.codes.2xx'] || 0;
  const failedRequests = counters['http.errors'] || 0;
  const timeouts = counters['http.errors.ETIMEDOUT'] || 0;
  const successRate = totalRequests > 0 ? (successfulRequests / totalRequests * 100) : 0;

  // Response time metrics
  const responseTime = summaries['http.response_time'] || {};
  const responseTime2xx = summaries['http.response_time.2xx'] || {};
  const sessionLength = summaries['vusers.session_length'] || {};

  // Per-phase data
  const phases = intermediate.map((phase, index) => {
    const phaseCounters = phase.counters || {};
    const phaseSummaries = phase.summaries || {};
    const phaseRt = phaseSummaries['http.response_time'] || {};
    
    return {
      phase: index + 1,
      requests: phaseCounters['http.requests'] || 0,
      successful: phaseCounters['http.codes.200'] || phaseCounters['http.codes.2xx'] || 0,
      errors: phaseCounters['http.errors'] || 0,
      timeouts: phaseCounters['http.errors.ETIMEDOUT'] || 0,
      p50: phaseRt.median,
      p95: phaseRt.p95,
      p99: phaseRt.p99,
      mean: phaseRt.mean
    };
  });

  // Generate HTML
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Artillery Report: ${reportName}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
      padding: 2rem;
    }
    .container { max-width: 1200px; margin: 0 auto; }
    h1 { font-size: 2rem; margin-bottom: 0.5rem; color: #f8fafc; }
    .subtitle { color: #94a3b8; margin-bottom: 2rem; }
    
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }
    
    .metric-card {
      background: #1e293b;
      border-radius: 0.75rem;
      padding: 1.5rem;
      border: 1px solid #334155;
    }
    
    .metric-label {
      font-size: 0.875rem;
      color: #94a3b8;
      margin-bottom: 0.5rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    
    .metric-value {
      font-size: 1.75rem;
      font-weight: 700;
      color: #f8fafc;
    }
    
    .metric-value.good { color: #22c55e; }
    .metric-value.warning { color: #eab308; }
    .metric-value.critical { color: #ef4444; }
    
    .metric-detail {
      font-size: 0.75rem;
      color: #64748b;
      margin-top: 0.25rem;
    }
    
    .section {
      background: #1e293b;
      border-radius: 0.75rem;
      padding: 1.5rem;
      margin-bottom: 1.5rem;
      border: 1px solid #334155;
    }
    
    .section h2 {
      font-size: 1.25rem;
      margin-bottom: 1rem;
      color: #f8fafc;
    }
    
    table {
      width: 100%;
      border-collapse: collapse;
    }
    
    th, td {
      padding: 0.75rem 1rem;
      text-align: left;
      border-bottom: 1px solid #334155;
    }
    
    th {
      background: #0f172a;
      font-weight: 600;
      color: #94a3b8;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    
    td { color: #e2e8f0; }
    
    tr:hover { background: #334155; }
    
    .chart-container {
      position: relative;
      height: 300px;
      margin-top: 1rem;
    }
    
    .percentile-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 1rem;
    }
    
    .percentile-item {
      text-align: center;
      padding: 1rem;
      background: #0f172a;
      border-radius: 0.5rem;
    }
    
    .percentile-label {
      font-size: 0.75rem;
      color: #94a3b8;
      margin-bottom: 0.25rem;
    }
    
    .percentile-value {
      font-size: 1.25rem;
      font-weight: 600;
    }
    
    .timestamp {
      color: #64748b;
      font-size: 0.875rem;
      margin-top: 2rem;
      text-align: center;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>🚀 Artillery Load Test Report</h1>
    <p class="subtitle">${reportName} • Generated ${new Date().toISOString()}</p>
    
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-label">Total Requests</div>
        <div class="metric-value">${formatNumber(totalRequests)}</div>
        <div class="metric-detail">${formatNumber(successfulRequests)} successful</div>
      </div>
      
      <div class="metric-card">
        <div class="metric-label">Success Rate</div>
        <div class="metric-value" style="color: ${getStatusColor(successRate)}">${successRate.toFixed(2)}%</div>
        <div class="metric-detail">${formatNumber(failedRequests)} errors, ${formatNumber(timeouts)} timeouts</div>
      </div>
      
      <div class="metric-card">
        <div class="metric-label">p50 Latency</div>
        <div class="metric-value">${formatMs(responseTime.median)}</div>
        <div class="metric-detail">Median response time</div>
      </div>
      
      <div class="metric-card">
        <div class="metric-label">p95 Latency</div>
        <div class="metric-value" style="color: ${getLatencyColor(responseTime.p95)}">${formatMs(responseTime.p95)}</div>
        <div class="metric-detail">95th percentile</div>
      </div>
      
      <div class="metric-card">
        <div class="metric-label">p99 Latency</div>
        <div class="metric-value" style="color: ${getLatencyColor(responseTime.p99, {good: 1000, warning: 2000})}">${formatMs(responseTime.p99)}</div>
        <div class="metric-detail">99th percentile</div>
      </div>
      
      <div class="metric-card">
        <div class="metric-label">Max Latency</div>
        <div class="metric-value" style="color: ${getLatencyColor(responseTime.max, {good: 2000, warning: 5000})}">${formatMs(responseTime.max)}</div>
        <div class="metric-detail">Slowest request</div>
      </div>
    </div>
    
    <div class="section">
      <h2>📊 Response Time Distribution</h2>
      <div class="percentile-grid">
        <div class="percentile-item">
          <div class="percentile-label">Min</div>
          <div class="percentile-value">${formatMs(responseTime.min)}</div>
        </div>
        <div class="percentile-item">
          <div class="percentile-label">Mean</div>
          <div class="percentile-value">${formatMs(responseTime.mean)}</div>
        </div>
        <div class="percentile-item">
          <div class="percentile-label">Median (p50)</div>
          <div class="percentile-value">${formatMs(responseTime.median)}</div>
        </div>
        <div class="percentile-item">
          <div class="percentile-label">p75</div>
          <div class="percentile-value">${formatMs(getPercentile(responseTime, 'p75'))}</div>
        </div>
        <div class="percentile-item">
          <div class="percentile-label">p90</div>
          <div class="percentile-value">${formatMs(getPercentile(responseTime, 'p90'))}</div>
        </div>
        <div class="percentile-item">
          <div class="percentile-label">p95</div>
          <div class="percentile-value">${formatMs(responseTime.p95)}</div>
        </div>
        <div class="percentile-item">
          <div class="percentile-label">p99</div>
          <div class="percentile-value">${formatMs(responseTime.p99)}</div>
        </div>
        <div class="percentile-item">
          <div class="percentile-label">Max</div>
          <div class="percentile-value">${formatMs(responseTime.max)}</div>
        </div>
      </div>
    </div>
    
    ${phases.length > 0 ? `
    <div class="section">
      <h2>📈 Per-Phase Breakdown</h2>
      <div class="chart-container">
        <canvas id="phaseChart"></canvas>
      </div>
      <table style="margin-top: 1.5rem">
        <thead>
          <tr>
            <th>Phase</th>
            <th>Requests</th>
            <th>Successful</th>
            <th>Errors</th>
            <th>Timeouts</th>
            <th>p50</th>
            <th>p95</th>
            <th>p99</th>
          </tr>
        </thead>
        <tbody>
          ${phases.map(p => `
          <tr>
            <td>${p.phase}</td>
            <td>${formatNumber(p.requests)}</td>
            <td style="color: #22c55e">${formatNumber(p.successful)}</td>
            <td style="color: ${p.errors > 0 ? '#ef4444' : '#22c55e'}">${formatNumber(p.errors)}</td>
            <td style="color: ${p.timeouts > 0 ? '#ef4444' : '#22c55e'}">${formatNumber(p.timeouts)}</td>
            <td>${formatMs(p.p50)}</td>
            <td>${formatMs(p.p95)}</td>
            <td>${formatMs(p.p99)}</td>
          </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    ` : ''}
    
    <div class="section">
      <h2>📋 Raw Counters</h2>
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          ${Object.entries(counters).map(([key, value]) => `
          <tr>
            <td>${key}</td>
            <td>${formatNumber(value)}</td>
          </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    
    <p class="timestamp">Report generated from Artillery JSON output</p>
  </div>
  
  <script>
    // Phase chart
    const phaseData = ${JSON.stringify(phases)};
    if (phaseData.length > 0) {
      const ctx = document.getElementById('phaseChart').getContext('2d');
      new Chart(ctx, {
        type: 'bar',
        data: {
          labels: phaseData.map(p => 'Phase ' + p.phase),
          datasets: [{
            label: 'p50 Latency (ms)',
            data: phaseData.map(p => p.p50),
            backgroundColor: 'rgba(59, 130, 246, 0.7)',
            borderColor: 'rgba(59, 130, 246, 1)',
            borderWidth: 1
          }, {
            label: 'p95 Latency (ms)',
            data: phaseData.map(p => p.p95),
            backgroundColor: 'rgba(249, 115, 22, 0.7)',
            borderColor: 'rgba(249, 115, 22, 1)',
            borderWidth: 1
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              beginAtZero: true,
              grid: { color: 'rgba(148, 163, 184, 0.1)' },
              ticks: { color: '#94a3b8' }
            },
            x: {
              grid: { color: 'rgba(148, 163, 184, 0.1)' },
              ticks: { color: '#94a3b8' }
            }
          },
          plugins: {
            legend: {
              labels: { color: '#e2e8f0' }
            }
          }
        }
      });
    }
  </script>
</body>
</html>`;
}

function generateConsoleSummary(reportData, reportName) {
  const aggregate = reportData.aggregate || {};
  const counters = aggregate.counters || {};
  const summaries = aggregate.summaries || {};
  
  const totalRequests = counters['http.requests'] || 0;
  const successfulRequests = counters['http.codes.200'] || counters['http.codes.2xx'] || 0;
  const failedRequests = counters['http.errors'] || 0;
  const timeouts = counters['http.errors.ETIMEDOUT'] || 0;
  const successRate = totalRequests > 0 ? (successfulRequests / totalRequests * 100) : 0;
  
  const responseTime = summaries['http.response_time'] || {};
  
  console.log(`\n${colors.bright}${colors.cyan}═══════════════════════════════════════════════════════════${colors.reset}`);
  console.log(`${colors.bright}  Artillery Report: ${reportName}${colors.reset}`);
  console.log(`${colors.cyan}═══════════════════════════════════════════════════════════${colors.reset}\n`);
  
  console.log(`  ${colors.bright}Summary${colors.reset}`);
  console.log(`  ─────────────────────────────────────`);
  console.log(`  Total Requests:     ${colors.bright}${formatNumber(totalRequests)}${colors.reset}`);
  console.log(`  Successful:         ${successRate >= 99 ? colors.green : successRate >= 95 ? colors.yellow : colors.red}${formatNumber(successfulRequests)} (${successRate.toFixed(2)}%)${colors.reset}`);
  console.log(`  Errors:             ${failedRequests > 0 ? colors.red : colors.green}${formatNumber(failedRequests)}${colors.reset}`);
  console.log(`  Timeouts:           ${timeouts > 0 ? colors.red : colors.green}${formatNumber(timeouts)}${colors.reset}`);
  
  console.log(`\n  ${colors.bright}Latency${colors.reset}`);
  console.log(`  ─────────────────────────────────────`);
  console.log(`  Min:                ${formatMs(responseTime.min)}`);
  console.log(`  Mean:               ${formatMs(responseTime.mean)}`);
  console.log(`  Median (p50):       ${colors.bright}${formatMs(responseTime.median)}${colors.reset}`);
  console.log(`  p75:                ${formatMs(getPercentile(responseTime, 'p75'))}`);
  console.log(`  p90:                ${formatMs(getPercentile(responseTime, 'p90'))}`);
  console.log(`  p95:                ${colors.yellow}${formatMs(responseTime.p95)}${colors.reset}`);
  console.log(`  p99:                ${colors.red}${formatMs(responseTime.p99)}${colors.reset}`);
  console.log(`  Max:                ${formatMs(responseTime.max)}`);
  
  console.log(`\n${colors.cyan}═══════════════════════════════════════════════════════════${colors.reset}\n`);
}

// Main execution
const args = process.argv.slice(2);

if (args.length === 0) {
  console.log(`${colors.cyan}Artillery Report Generator${colors.reset}`);
  console.log(`\nUsage: node generate-report.js <report.json> [output.html]`);
  console.log(`\nIf output.html is not specified, generates <report-name>.html`);
  console.log(`\nOptions:`);
  console.log(`  --console    Only print console summary, don't generate HTML`);
  process.exit(0);
}

const inputFile = args[0];
const consoleOnly = args.includes('--console');

if (!fs.existsSync(inputFile)) {
  console.error(`${colors.red}Error: File not found: ${inputFile}${colors.reset}`);
  process.exit(1);
}

try {
  const reportData = JSON.parse(fs.readFileSync(inputFile, 'utf8'));
  const reportName = path.basename(inputFile, '.json');
  
  // Always show console summary
  generateConsoleSummary(reportData, reportName);
  
  if (!consoleOnly) {
    const outputFile = args[1] || `${reportName}.html`;
    const html = generateHTML(reportData, reportName);
    fs.writeFileSync(outputFile, html);
    console.log(`${colors.green}✓ HTML report generated: ${outputFile}${colors.reset}`);
  }
} catch (err) {
  console.error(`${colors.red}Error processing report: ${err.message}${colors.reset}`);
  process.exit(1);
}
