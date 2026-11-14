import type { ActionConversation, ConversationResume, Message } from './api'

export function trier(liste: ConversationResume[]): ConversationResume[] {
  return [...liste].sort((a, b) => b.maj_le.localeCompare(a.maj_le))
}

export type ElementFil =
  | { type: 'message'; message: Message }
  | { type: 'action'; action: ActionConversation }

export function fil(messages: Message[], actions: ActionConversation[]): ElementFil[] {
  const l: ElementFil[] = [
    ...messages.map((message) => ({ type: 'message' as const, message })),
    ...actions.map((action) => ({ type: 'action' as const, action })),
  ]
  const o = (e: ElementFil) => (e.type === 'message' ? e.message : e.action)
  return l.sort((x, y) => o(x).cree_le.localeCompare(o(y).cree_le) || o(x).id - o(y).id)
}

export function libelleAction(a: ActionConversation): string {
  const p = a.parametres
  switch (a.nom) {
    case 'creer_projet': return `Créer le projet « ${p.nom} »`
    case 'deposer_spec': return `Déposer et valider la spec du projet n°${p.projet_id}`
    case 'lancer_pipeline': return `Lancer le pipeline ${p.type} sur le projet n°${p.projet_id}`
    case 'creer_tache': return `Créer la tâche « ${p.titre} »`
    case 'modifier_tache': return `Modifier la tâche n°${p.tache_id}`
    case 'deplacer_tache': return `Déplacer la tâche n°${p.tache_id} vers ${p.colonne}`
    case 'annuler_tache': return `Annuler la tâche n°${p.tache_id}`
    default: return a.nom
  }
}
