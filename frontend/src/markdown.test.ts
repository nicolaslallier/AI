import { describe, expect, it } from 'vitest'
import { rendreMarkdown, sansBlocModele } from './markdown'
import { urlDocumentArchitecture, urlModeleArchimate } from './api'

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

describe('sansBlocModele', () => {
  it('retire le dernier bloc json', () => {
    expect(sansBlocModele('Texte\n\n```json\n{"a":1}\n```\n').trim()).toBe('Texte')
  })
  it('garde un bloc json qui n’est pas le dernier', () => {
    const md = 'A\n\n```json\n{"a":1}\n```\n\nB\n\n```json\n{"b":2}\n```\n'
    expect(sansBlocModele(md)).toBe('A\n\n```json\n{"a":1}\n```\n\nB')
  })
  it('rend le texte tel quel sans bloc', () => {
    expect(sansBlocModele('Texte')).toBe('Texte')
  })
  it('ignore une mention en ligne qui n’est pas une clôture', () => {
    const md = 'Écris un bloc ```json puis du texte.\n\n```\ncode\n```\n'
    expect(sansBlocModele(md)).toBe(md)
  })
  it('retire le bloc avec des fins de ligne Windows', () => {
    expect(sansBlocModele('Texte\r\n\r\n```json\r\n{"a":1}\r\n```\r\n')).toBe('Texte')
  })
  it('laisse tel quel un bloc json non refermé', () => {
    const md = 'Texte\n\n```json\n{"a":1}\n'
    expect(sansBlocModele(md)).toBe(md)
  })
})

describe('liens du document d’architecture', () => {
  it('pointe vers les deux routes du pipeline', () => {
    expect(urlModeleArchimate(7)).toBe('/api/pipelines/7/architecture.xml')
    expect(urlDocumentArchitecture(7)).toBe('/api/pipelines/7/architecture.md')
  })
})
