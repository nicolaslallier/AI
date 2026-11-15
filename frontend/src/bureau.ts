import type { Poste } from './api'

/** État du conteneur d'un agent, en toutes lettres (jamais la couleur seule) ; rien pour un agent du portail. */
export function libelleConteneur(c: Poste['conteneur'] | undefined): string {
  if (!c) return ''
  if (!c.repond) return 'conteneur injoignable'
  return c.version ? `conteneur ● ${c.version}` : 'conteneur ●'
}
