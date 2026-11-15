export interface RappelsEvenements {
  kanban?: (projetId: number | null) => void
  pipelines?: () => void
  bureau?: () => void
}

// le navigateur se reconnecte seul ; le sondage de secours des vues couvre les trous
export function ecouterEvenements(rappels: RappelsEvenements): () => void {
  const source = new EventSource('/api/evenements')
  source.addEventListener('kanban', (e) =>
    rappels.kanban?.(JSON.parse((e as MessageEvent).data).projet_id ?? null),
  )
  source.addEventListener('pipelines', () => rappels.pipelines?.())
  source.addEventListener('bureau', () => rappels.bureau?.())
  return () => source.close()
}

/** Un seul appel après une rafale de signaux. */
export function regrouper(f: () => void, ms = 300): () => void {
  let minuteur: ReturnType<typeof setTimeout> | undefined
  return () => {
    clearTimeout(minuteur)
    minuteur = setTimeout(f, ms)
  }
}
