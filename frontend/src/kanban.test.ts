import { expect, it } from 'vitest'
import { COLONNES, filtrer, grouperParColonne } from './kanban'
import type { Tache } from './api'

const t = (id: number, colonne: string, rang: number, titre = 'x', description = ''): Tache => ({
  id, projet_id: 1, titre, description, criteres: [], fichiers: [], colonne, rang, origine: 'nicolas',
  document_id: null, protegee: false, verrou: null, version: 1, cree_le: '', maj_le: '',
  depend_de: [], dependances_non_terminees: [],
})

it('grouperParColonne donne les six clés, triées par rang', () => {
  const g = grouperParColonne([t(1, 'prete', 2000), t(2, 'prete', 1000), t(3, 'terminee', 1000)])
  expect(Object.keys(g)).toEqual(COLONNES.map((c) => c.valeur))
  expect(COLONNES).toHaveLength(6)
  expect(g.prete.map((x) => x.id)).toEqual([2, 1])
  expect(g.a_faire).toEqual([])
})

it('filtrer ignore casse et accents, titre et description', () => {
  const l = [t(1, 'a_faire', 1, 'Étape 2'), t(2, 'a_faire', 2, 'autre', 'une ETAPE'), t(3, 'a_faire', 3, 'rien')]
  expect(filtrer(l, 'etape').map((x) => x.id)).toEqual([1, 2])
  expect(filtrer(l, '  ')).toHaveLength(3)
})
