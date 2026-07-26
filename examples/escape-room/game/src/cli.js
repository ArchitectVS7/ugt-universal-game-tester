/**
 * cli.js — human-facing REPL front end.
 *
 * Translation layer only: reads a line, hands it to the engine, prints the
 * result. No rules here (see src/engine.js). The real free-text parser
 * (8 verbs + direction shorthands) arrives in T-005; this scaffold just
 * proves the wiring and the clean-exit behavior.
 */

import { createInterface } from 'node:readline';

import { executeCommand } from './engine.js';

const rl = createInterface({
  input: process.stdin,
  output: process.stdout,
  prompt: '> ',
});

console.log('Tiny Escape Room. Type a command, or press Ctrl+D to quit.');
rl.prompt();

rl.on('line', (line) => {
  const input = line.trim();
  if (input === '') {
    rl.prompt();
    return;
  }

  const spaceAt = input.indexOf(' ');
  const verb = spaceAt === -1 ? input : input.slice(0, spaceAt);
  const arg = spaceAt === -1 ? '' : input.slice(spaceAt + 1).trim();

  try {
    executeCommand(null, verb, arg);
  } catch (err) {
    console.log(err.message);
  }

  rl.prompt();
});

rl.on('close', () => {
  console.log('Goodbye.');
  process.exit(0);
});
