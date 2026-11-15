import type { Avis } from './api'

const rang = (a: Avis) => (a.etat === 'en_cours' ? 0 : a.etat === 'ouvert' ? 1 : 2)

/** Les avis en cours, puis les ouverts, puis le reste ; les plus récents (`id` décroissant) en tête de chaque groupe. */
export function trierAvis(avis: Avis[]): Avis[] {
  return [...avis].sort((a, b) => rang(a) - rang(b) || b.id - a.id)
}
