import { readFile } from 'node:fs/promises'

const path = new URL('../src/pages/PrerequisiteGraph.jsx', import.meta.url)
const source = await readFile(path, 'utf8')
const unsupported = [...source.matchAll(/['"](shadow-(?:blur|color|opacity|offset-x|offset-y))['"]\s*:/g)]

if (unsupported.length) {
  console.error(`Cytoscape style gate failed: unsupported properties: ${unsupported.map(match => match[1]).join(', ')}`)
  process.exit(1)
}

console.log('Cytoscape style gate passed: no unsupported shadow properties.')
