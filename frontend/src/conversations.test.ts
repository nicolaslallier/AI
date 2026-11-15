import { expect, it } from 'vitest'
import type { ActionConversation, ConversationResume, Message } from './api'
import { fil, libelleAction, trier } from './conversations'

const c = (id: number, maj_le: string): ConversationResume => ({ id, agent: 'orchestrateur', titre: `c${id}`, etat: 'pret', maj_le })

it('trier met la plus récente en premier sans muter', () => {
  const liste = [c(1, '2026-01-01T10:00:00'), c(2, '2026-03-01T10:00:00'), c(3, '2026-02-01T10:00:00')]
  expect(trier(liste).map((x) => x.id)).toEqual([2, 3, 1])
  expect(liste.map((x) => x.id)).toEqual([1, 2, 3])
})

const m = (id: number, cree_le: string): Message => ({ id, role: 'user', contenu: '', outil: null, cree_le })
const a = (id: number, nom: string, parametres: Record<string, unknown>, cree_le = '2026-01-01T10:00:00'): ActionConversation => ({
  id, nom, parametres, etat: 'proposee', resultat: null, lien: null, cree_le,
})

it('fil intercale les actions selon cree_le puis id', () => {
  const r = fil(
    [m(1, '2026-01-01T10:00:00'), m(2, '2026-01-01T10:00:02')],
    [a(1, 'creer_projet', {}, '2026-01-01T10:00:01')],
  )
  expect(r.map((x) => x.type)).toEqual(['message', 'action', 'message'])
})

it('libelleAction en français', () => {
  expect(libelleAction(a(1, 'creer_projet', { nom: 'EA' }))).toBe('Créer le projet « EA »')
  expect(libelleAction(a(2, 'deplacer_tache', { tache_id: 7, colonne: 'prete' }))).toBe('Déplacer la tâche n°7 vers prete')
})
