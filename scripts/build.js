import { cpSync, mkdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const distDir = path.join(projectRoot, 'dist');

rmSync(distDir, { recursive: true, force: true });
mkdirSync(distDir, { recursive: true });

const copyEntries = [
  ['index.html', 'index.html'],
  ['src', 'src'],
  ['public', 'public'],
  ['trades.csv', 'trades.csv'],
];

for (const [source, destination] of copyEntries) {
  const sourcePath = path.join(projectRoot, source);
  try {
    cpSync(sourcePath, path.join(distDir, destination), { recursive: true });
  } catch (error) {
    if (error && error.code === 'ENOENT') {
      continue;
    }
    throw error;
  }
}

console.log('Static build complete: dist/ is ready to serve.');
