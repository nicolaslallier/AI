import type { Tache } from './api'

export const COLONNES = [
  { valeur: 'a_faire', libelle: 'À faire' },
  { valeur: 'prete', libelle: 'Prête' },
  { valeur: 'en_cours', libelle: 'En cours' },
  { valeur: 'en_revue', libelle: 'En revue' },
  { valeur: 'terminee', libelle: 'Terminée' },
  { valeur: 'bloquee', libelle: 'Bloquée' },
]

export function grouperParColonne(taches: Tache[]): Record<string, Tache[]> {
  const g: Record<string, Tache[]> = Object.fromEntries(COLONNES.map((c) => [c.valeur, []]))
  for (const t of [...taches].sort((a, b) => a.rang - b.rang)) (g[t.colonne] ??= []).push(t)
  return g
}

const norm = (s: string) => s.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()

export function filtrer(taches: Tache[], texte: string): Tache[] {
  const q = norm(texte.trim())
  if (!q) return taches
  return taches.filter((t) => norm(t.titre + '\n' + t.description).includes(q))
}
