export interface RappelsFlux {
  partiel(t: string): void
  delta(t: string): void
  fin(): void
  erreur(m: string): void
}

export function ecouterFlux(etapeId: number, rappels: RappelsFlux): () => void {
  const source = new EventSource(`/api/etapes/${etapeId}/flux`)
  let termine = false
  const donnee = (e: Event) => JSON.parse((e as MessageEvent).data)
  source.addEventListener('partiel', (e) => rappels.partiel(donnee(e).texte))
  source.addEventListener('delta', (e) => rappels.delta(donnee(e).texte))
  source.addEventListener('fin', () => {
    termine = true
    source.close()
    rappels.fin()
  })
  source.addEventListener('erreur', (e) => {
    termine = true
    source.close()
    rappels.erreur(donnee(e).message)
  })
  // le navigateur se reconnecte seul tant que readyState n'est pas CLOSED ; on ne boucle pas
  source.onerror = () => {
    if (termine || source.readyState !== 2) return
    termine = true
    rappels.erreur('connexion perdue')
  }
  return () => {
    termine = true
    source.close()
  }
}
