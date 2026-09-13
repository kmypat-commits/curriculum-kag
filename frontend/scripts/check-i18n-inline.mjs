import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../src/', import.meta.url))
async function files(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const result = []
  for (const entry of entries) {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) result.push(...await files(path))
    else if (/\.(jsx|js)$/.test(entry.name)) result.push(path)
  }
  return result
}

const sourceFiles = await files(root)
let count = 0
const offenders = []
let localeHelperCount = 0
const localeHelperOffenders = []
for (const path of sourceFiles) {
  const source = await readFile(path, 'utf8')
  const matches = source.match(/\blocalText\s*\(/g) || []
  const helperMatches = source.match(/(?:const|function)\s+(?:l|localText)\s*=??\s*\(?\s*(?:ru|kk|en)\b/g) || []
  if (matches.length) {
    count += matches.length
    offenders.push(`${path}: ${matches.length}`)
  }
  if (helperMatches.length) {
    localeHelperCount += helperMatches.length
    localeHelperOffenders.push(`${path}: ${helperMatches.length}`)
  }
}

console.log(`i18n inline-language calls: ${count}`)
console.log(`i18n local locale helpers: ${localeHelperCount}`)
if (localeHelperCount > 0) {
  console.error('i18n gate failed: local ru/kk/en helpers remain; migrate their user-facing strings to translations.js.')
  console.error(localeHelperOffenders.join('\n'))
  process.exit(1)
}
if (count > 0) {
  console.error('i18n gate failed: inline-language usage remains; add catalog keys instead.')
  console.error(offenders.join('\n'))
  process.exit(1)
}
