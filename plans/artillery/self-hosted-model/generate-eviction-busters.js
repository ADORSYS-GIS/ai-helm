#!/usr/bin/env node
/**
 * Generates eviction-busters.csv — ~20 unique large system prompts (~8000 tokens
 * each) used as cache-busters in Experiment B. Each prompt is on a distinct topic
 * with a unique random identifier so no prefix tokens are shared across entries.
 *
 * Run from plans/artillery/self-hosted-model/:
 *   node generate-eviction-busters.js
 *
 * Output: eviction-busters.csv (columns: system_prompt, question)
 */

const fs = require('fs');
const crypto = require('crypto');

// Each topic gets a unique ~8000-token system prompt built from repeated
// paragraphs with slight variations. At ~4 chars/token, ~32,000 chars → ~8000 tokens.
const TOPICS = [
  { subject: 'the French Revolution', focus: 'the Reign of Terror' },
  { subject: 'solar energy technology', focus: 'perovskite solar cells' },
  { subject: 'deep ocean hydrothermal vents', focus: 'chemosynthetic ecosystems' },
  { subject: 'medieval Gothic architecture', focus: 'flying buttress design' },
  { subject: 'machine learning optimization', focus: 'gradient descent variants' },
  { subject: 'the human immune system', focus: 'T-cell activation pathways' },
  { subject: 'plate tectonics', focus: 'subduction zone dynamics' },
  { subject: 'baroque music composition', focus: 'fugal counterpoint techniques' },
  { subject: 'quantum entanglement', focus: 'Bell inequality experiments' },
  { subject: 'the Silk Road trade network', focus: 'caravan logistics and taxation' },
  { subject: 'CRISPR gene editing', focus: 'off-target effect mitigation' },
  { subject: 'Byzantine fault tolerance', focus: 'Paxos consensus protocol' },
  { subject: 'coral reef bleaching', focus: 'zooxanthellae symbiosis breakdown' },
  { subject: 'the Mongol Empire', focus: 'relay station postal system' },
  { subject: 'protein folding', focus: 'alpha-helix stability factors' },
  { subject: 'Roman concrete', focus: 'pozzolanic ash durability' },
  { subject: 'black hole thermodynamics', focus: 'Hawking radiation' },
  { subject: 'the Gutenberg printing press', focus: 'movable type metallurgy' },
  { subject: 'neural network pruning', focus: 'magnitude-based weight pruning' },
  { subject: 'the Minoan civilization', focus: 'Linear A script decipherment' },
];

const QUESTIONS = [
  'What is the main unresolved challenge?',
  'How has understanding evolved over the past decade?',
  'What methodology is most promising?',
  'What is the most surprising recent finding?',
  'What are the practical implications?',
];

function generatePrompt(topic, index) {
  const id = crypto.randomBytes(20).toString('hex');
  const num = String(index + 1).padStart(4, '0');

  // Build ~2000 tokens of unique text by repeating structured paragraphs
  // with incrementing section numbers. Each paragraph is ~120 tokens.
  // 17 paragraphs × ~120 tokens ≈ ~2000 tokens.
  const paragraphs = [];
  paragraphs.push(
    `Reference identifier ${id}. You are an expert educator and researcher. ` +
    `Discuss ${topic.subject} with particular emphasis on ${topic.focus}. ` +
    `Provide context about the historical development, current state of the field, ` +
    `key challenges, methodological considerations, and future research directions. ` +
    `Request #${num}: please structure your answer with clear sections.`
  );

  for (let i = 1; i <= 16; i++) {
    paragraphs.push(
      `Section ${i}. In the context of ${topic.focus} within the broader field of ` +
      `${topic.subject}, several key aspects merit detailed examination. ` +
      `The theoretical foundations rest on principles established through decades ` +
      `of research and empirical observation. Researchers have identified multiple ` +
      `factors that influence outcomes, including environmental conditions, ` +
      `resource availability, competing theoretical models, and the limitations ` +
      `of current experimental methodologies. The interplay between these factors ` +
      `creates a complex landscape that requires careful analysis. ` +
      `Study number ${i * 100 + index} demonstrated that results can vary significantly ` +
      `based on initial conditions and the specific parameters chosen for investigation. ` +
      `This finding has been replicated across multiple independent research groups, ` +
      `lending credibility to the conclusions while also highlighting the sensitivity ` +
      `of the system to perturbations. The implications extend beyond the immediate ` +
      `domain and connect to broader questions about ${topic.subject} that remain ` +
      `actively debated in the literature today.`
    );
  }

  return paragraphs.join(' ');
}

const rows = ['system_prompt,question'];
TOPICS.forEach((topic, i) => {
  const prompt = generatePrompt(topic, i);
  const question = QUESTIONS[i % QUESTIONS.length];
  // CSV-safe: wrap in double quotes, escape internal double quotes
  const safePrompt = '"' + prompt.replace(/"/g, '""') + '"';
  const safeQuestion = '"' + question.replace(/"/g, '""') + '"';
  rows.push(`${safePrompt},${safeQuestion}`);
});

const csv = rows.join('\n') + '\n';
const outFile = __dirname + '/eviction-busters.csv';
fs.writeFileSync(outFile, csv);
console.log(`Generated ${TOPICS.length} buster prompts → ${outFile}`);
console.log(`File size: ${(csv.length / 1024).toFixed(1)} KiB`);
console.log(`Approximate tokens per prompt: ~2000`);