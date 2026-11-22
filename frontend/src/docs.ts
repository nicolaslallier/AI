import type { CarteDoc } from './api'

export const COLONNES_DOC = [
  { valeur: 'a_rediger', libelle: 'À rédiger' },
  { valeur: 'redaction', libelle: 'Rédaction' },
  { valeur: 'revue', libelle: 'Revue' },
  { valeur: 'a_valider', libelle: 'À valider' },
  { valeur: 'publie', libelle: 'Publié' },
]

export const GENRES = ['readme', 'architecture', 'runbook', 'adr', 'api', 'guide', 'autre']

export const EN_COURS = ['redaction', 'revue']

export function grouper(cartes: CarteDoc[]): Record<string, CarteDoc[]> {
  const g: Record<string, CarteDoc[]> = Object.fromEntries(COLONNES_DOC.map((c) => [c.valeur, []]))
  for (const c of [...cartes].sort((a, b) => a.id - b.id)) (g[c.colonne] ??= []).push(c)
  return g
}

/** Le contenu a changé côté serveur : le brouillon suit seulement s'il n'a pas été modifié. */
export function resynchroniser(brouillon: string, base: string, nouveau: string): { brouillon: string; base: string } {
  return brouillon === base ? { brouillon: nouveau, base: nouveau } : { brouillon, base: nouveau }
}
