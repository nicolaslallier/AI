import { expect, it } from 'vitest'
import type { ConversationResume } from './api'
import { trier } from './conversations'

const c = (id: number, maj_le: string): ConversationResume => ({ id, titre: `c${id}`, etat: 'pret', maj_le })

it('trier met la plus récente en premier sans muter', () => {
  const liste = [c(1, '2026-01-01T10:00:00'), c(2, '2026-03-01T10:00:00'), c(3, '2026-02-01T10:00:00')]
  expect(trier(liste).map((x) => x.id)).toEqual([2, 3, 1])
  expect(liste.map((x) => x.id)).toEqual([1, 2, 3])
})
