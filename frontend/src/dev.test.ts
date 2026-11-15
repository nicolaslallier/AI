import { expect, it } from 'vitest'
import { duree, emplacement, extrait, numeroPr } from './dev'

it('duree : secondes, minutes, en cours', () => {
  expect(duree('2026-01-01T10:00:00Z', '2026-01-01T10:00:12Z')).toBe('12 s')
  expect(duree('2026-01-01T10:00:00Z', '2026-01-01T10:03:04Z')).toBe('3 min 4 s')
  expect(duree('2026-01-01T10:00:00Z', null)).toBe('en cours')
})

it('numeroPr extrait le numéro de l’URL', () => {
  expect(numeroPr('https://github.com/o/r/pull/42')).toBe('PR #42')
  expect(numeroPr('https://github.com/o/r/pull/42/')).toBe('PR #42')
  expect(numeroPr('https://github.com/o/r')).toBe('PR')
})

it('extrait : court inchangé, long coupé avec …', () => {
  expect(extrait('bonjour')).toBe('bonjour')
  const long = extrait('a'.repeat(300))
  expect(long).toHaveLength(281)
  expect(long.endsWith('…')).toBe(true)
})

it('emplacement : fichier:ligne, revue ou conversation', () => {
  expect(emplacement({ type: 'ligne', chemin: 'src/a.py', ligne: 12 })).toBe('src/a.py:12')
  expect(emplacement({ type: 'revue', chemin: null, ligne: null })).toBe('revue')
  expect(emplacement({ type: 'conversation', chemin: null, ligne: null })).toBe('conversation')
})
