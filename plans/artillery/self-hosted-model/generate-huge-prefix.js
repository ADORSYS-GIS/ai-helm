#!/usr/bin/env node
/**
 * Generates huge-prefix.csv — a single-row payload containing the FULL text of
 * docs/lmcache+vllm.md (~7.2K tokens) wrapped as a "summarise on demand" system
 * prompt. Used by artillery-qwen25-huge-prefix.yml.
 *
 * The shared prefix is so large that:
 *   - APC barely holds it (~252 MiB of the ~1.3 GiB GPU KV budget at 0.55 util)
 *   - Once APC evicts it, LMCache retrieving ~7K tokens from CPU RAM at ~10ms
 *     produces a dramatic delta vs the baseline's multi-second full re-prefill.
 *
 * Prerequisites:
 *   docs/lmcache+vllm.md must exist in the repo root. This file is the KV cache
 *   reference document (~38 KiB, ~9.7K tokens including the wrapper instruction)
 *   used as the shared system prompt. It is NOT committed to the public repo.
 *   To regenerate huge-prefix.csv you need a local copy. The committed
 *   huge-prefix.csv is the canonical artifact for CI — re-run this script only
 *   when the source document changes.
 *
 *   If you do not have docs/lmcache+vllm.md, the committed huge-prefix.csv in
 *   this directory can be used directly by artillery-qwen25-huge-prefix.yml
 *   without re-running this generator.
 *
 * Run from plans/artillery/self-hosted-model/:
 *   node generate-huge-prefix.js
 *
 * Output: huge-prefix.csv (columns: huge_prefix)
 */
const fs = require('fs');
const path = require('path');

const docPath = path.resolve(__dirname, '../../../docs/lmcache+vllm.md');

if (!fs.existsSync(docPath)) {
  console.error(`ERROR: source document not found: ${docPath}`);
  console.error('');
  console.error('huge-prefix.csv requires docs/lmcache+vllm.md (the KV cache reference doc,');
  console.error('~38 KiB / ~9.7K tokens). This file is not committed to the public repo.');
  console.error('');
  console.error('Options:');
  console.error('  1. Use the committed huge-prefix.csv directly — it is the correct artifact');
  console.error('     and is already referenced by artillery-qwen25-huge-prefix.yml.');
  console.error('  2. Provide docs/lmcache+vllm.md locally and re-run this script to regenerate.');
  process.exit(1);
}

const docText = fs.readFileSync(docPath, 'utf8');

const systemPrompt =
  'You are an expert technical writer and LLM infrastructure architect. ' +
  'A reference document is provided below between explicit delimiters. ' +
  'When the user asks a question, answer it by reasoning about the document ' +
  'content. Be precise, cite specific facts, numbers, and section titles. ' +
  'Do not speculate beyond what the document states. Keep responses concise — ' +
  'at most a few sentences unless asked for detail.\n\n' +
  '--- BEGIN REFERENCE DOCUMENT ---\n\n' +
  docText +
  '\n\n--- END REFERENCE DOCUMENT ---\n';

function csvQuote(s) {
  return '"' + String(s).replace(/"/g, '""') + '"';
}

const row = csvQuote(systemPrompt);
const csv = 'huge_prefix\n' + row + '\n';

const outFile = __dirname + '/huge-prefix.csv';
fs.writeFileSync(outFile, csv);
console.log(`Wrote ${outFile}`);
console.log(`File size: ${(csv.length / 1024).toFixed(1)} KiB`);
console.log(`System prompt chars: ${systemPrompt.length}`);
console.log(`Approximate tokens: ~${Math.round(systemPrompt.length / 4)}`);
