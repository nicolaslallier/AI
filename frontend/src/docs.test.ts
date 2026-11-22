import { expect, it } from 'vitest'
import { COLONNES_DOC, grouper, resynchroniser } from './docs'
import type { CarteDoc } from './api'

const c = (id: number, colonne: string): CarteDoc => ({
  id, projet_id: 1, projet_nom: 'p', titre: 't', genre: 'guide', consigne: '', colonne, chemin: `c${id}`,
  contenu: '', remarques: [], renvois: 0, sha: null, pipeline_id: null, erreur: null, publie_le: null, maj_le: '',
})

it('grouper donne les cinq colonnes, triées par id', () => {
  const g = grouper([c(3, 'a_valider'), c(1, 'a_valider'), c(2, 'publie')])
  expect(Object.keys(g)).toEqual(COLONNES_DOC.map((x) => x.valeur))
  expect(g.a_valider.map((x) => x.id)).toEqual([1, 3])
  expect(g.a_rediger).toEqual([])
})

it('resynchroniser suit le serveur sans écraser une édition', () => {
  expect(resynchroniser('a', 'a', 'b')).toEqual({ brouillon: 'b', base: 'b' })
  expect(resynchroniser('tapé', 'a', 'b')).toEqual({ brouillon: 'tapé', base: 'b' })
})
