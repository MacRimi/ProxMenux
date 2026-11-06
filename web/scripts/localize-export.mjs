// Next's shared root layout cannot read its nested [locale] parameter.
// Set the static document language before Pagefind indexes the export, so
// search and no-JavaScript readers see the same locale as the hydrated app.
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

async function htmlFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = await Promise.all(entries.map(entry => {
    const path = join(directory, entry.name)
    return entry.isDirectory() ? htmlFiles(path) : entry.isFile() && entry.name.endsWith('.html') ? [path] : []
  }))
  return files.flat()
}

let count = 0
for (const entry of await readdir('out', { withFileTypes: true })) {
  if (!entry.isDirectory() || !/^[a-z]{2}(?:-[a-z0-9]+)?$/.test(entry.name)) continue
  const locale = entry.name
  for (const file of await htmlFiles(join('out', locale))) {
    const original = await readFile(file, 'utf8')
    const updated = original.replace(/<html\b([^>]*)>/i, (tag, attributes) => {
      const next = /\blang\s*=\s*["'][^"']*["']/i.test(attributes)
        ? attributes.replace(/\blang\s*=\s*["'][^"']*["']/i, `lang="${locale}"`)
        : `${attributes} lang="${locale}"`
      return `<html${next}>`
    })
    if (updated !== original) await writeFile(file, updated, 'utf8')
    count += 1
  }
}
console.log(`Static document language verified for ${count} localized pages.`)
