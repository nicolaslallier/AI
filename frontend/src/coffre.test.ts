import { describe, expect, it } from 'vitest'
import { separerFrontmatter } from './coffre'

describe('separerFrontmatter', () => {
  it('sépare le frontmatter du corps', () => {
    expect(separerFrontmatter('---\ntype: doc\nprojet: P\n---\n# Titre\n')).toEqual({
      frontmatter: 'type: doc\nprojet: P',
      corps: '# Titre\n',
    })
  })
  it('sans frontmatter, tout est corps', () => {
    expect(separerFrontmatter('# T\n---\nx')).toEqual({ frontmatter: '', corps: '# T\n---\nx' })
  })
  it('frontmatter non refermé : laissé dans le corps', () => {
    expect(separerFrontmatter('---\na: 1\n# T')).toEqual({ frontmatter: '', corps: '---\na: 1\n# T' })
  })
  it('accepte CRLF et note réduite au frontmatter', () => {
    expect(separerFrontmatter('---\r\na: 1\r\n---')).toEqual({ frontmatter: 'a: 1', corps: '' })
  })
})
