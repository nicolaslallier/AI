import { expect, it } from 'vitest'
import type { Avis } from './api'
import { trierAvis } from './avis'

const a = (id: number, etat: string): Avis => ({ id, agent: 'architecte', contenu: '', etat, version: 1, ancienne: false })

it('trierAvis met les en_cours puis les ouvert d\'abord, les plus récents en tête, sans muter', () => {
  const liste = [a(1, 'ouvert'), a(2, 'ecarte'), a(3, 'en_cours'), a(4, 'ouvert'), a(5, 'pris_en_compte'), a(6, 'en_cours')]
  expect(trierAvis(liste).map((x) => x.id)).toEqual([6, 3, 4, 1, 5, 2])
  expect(liste.map((x) => x.id)).toEqual([1, 2, 3, 4, 5, 6])
})
