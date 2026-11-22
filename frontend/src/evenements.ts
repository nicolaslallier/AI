export interface RappelsEvenements {
  kanban?: (projetId: number | null) => void
  pipelines?: () => void
  bureau?: () => void
  docs?: () => void
}

// le navigateur se reconnecte seul ; le sondage de secours des vues couvre les trous
export function ecouterEvenements(rappels: RappelsEvenements): () => void {
  const source = new EventSource('/api/evenements')
  source.addEventListener('kanban', (e) =>
    rappels.kanban?.(JSON.parse((e as MessageEvent).data).projet_id ?? null),
  )
  source.addEventListener('pipelines', () => rappels.pipelines?.())
  source.addEventListener('bureau', () => rappels.bureau?.())
  source.addEventListener('docs', () => rappels.docs?.())
  return () => source.close()
}

/** Au plus un appel par fenêtre de `ms` : une rafale continue finit quand même par appeler. */
export function regrouper(f: () => void, ms = 300): () => void {
  let minuteur: ReturnType<typeof setTimeout> | undefined
  return () => {
    minuteur ??= setTimeout(() => {
      minuteur = undefined
      f()
    }, ms)
  }
}
