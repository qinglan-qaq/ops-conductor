import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const featuresDir = join(process.cwd(), 'src', 'features')

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return files(path)
    return /\.(ts|vue)$/.test(entry.name) ? [path] : []
  })
}

describe('frontend layering', () => {
  it('does not import the API client or call fetch from features', () => {
    const offenders = files(featuresDir).filter((path) => {
      const source = readFileSync(path, 'utf8')
      return /from\s+['"]@\/api\/client['"]/.test(source) || /\bfetch\(/.test(source)
    })

    expect(offenders).toEqual([])
  })
})
