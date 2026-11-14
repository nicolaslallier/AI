import { describe, expect, it } from 'vitest'
import { rendreMarkdown } from './markdown'

describe('rendreMarkdown', () => {
  it('rend un titre', () => {
    expect(rendreMarkdown('# T')).toContain('<h1>')
  })
  it('retire les gestionnaires onerror', () => {
    expect(rendreMarkdown('<img src=x onerror=alert(1)>')).not.toContain('onerror')
  })
  it('retire les scripts', () => {
    expect(rendreMarkdown('<script>alert(1)</script>')).not.toContain('<script')
  })
})
