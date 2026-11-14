import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ecouterFlux } from './flux'

class FauxEventSource {
  static derniere: FauxEventSource
  readyState = 1
  close = vi.fn(() => {
    this.readyState = 2
  })
  onerror: (() => void) | null = null
  ecouteurs: Record<string, (e: { data: string }) => void> = {}
  constructor(public url: string) {
    FauxEventSource.derniere = this
  }
  addEventListener(nom: string, f: (e: { data: string }) => void) {
    this.ecouteurs[nom] = f
  }
  emettre(nom: string, data: unknown = {}) {
    this.ecouteurs[nom]({ data: JSON.stringify(data) })
  }
}

let rappels: { partiel: any; delta: any; fin: any; erreur: any; outil: any }
beforeEach(() => {
  ;(globalThis as any).EventSource = FauxEventSource
  rappels = { partiel: vi.fn(), delta: vi.fn(), fin: vi.fn(), erreur: vi.fn(), outil: vi.fn() }
})
afterEach(() => vi.restoreAllMocks())

it('partiel puis delta appellent les rappels', () => {
  ecouterFlux(7, rappels)
  const s = FauxEventSource.derniere
  expect(s.url).toBe('/api/etapes/7/flux')
  s.emettre('partiel', { texte: 'Bon' })
  s.emettre('delta', { texte: 'jour' })
  expect(rappels.partiel).toHaveBeenCalledWith('Bon')
  expect(rappels.delta).toHaveBeenCalledWith('jour')
})

it('outil appelle outil(libelle)', () => {
  ecouterFlux(1, rappels)
  FauxEventSource.derniere.emettre('outil', { libelle: 'lire(README.md)' })
  expect(rappels.outil).toHaveBeenCalledWith('lire(README.md)')
})

it('fin appelle fin() puis ferme', () => {
  ecouterFlux(1, rappels)
  const s = FauxEventSource.derniere
  s.emettre('fin')
  expect(rappels.fin).toHaveBeenCalledOnce()
  expect(s.close).toHaveBeenCalled()
})

it('erreur appelle erreur(message) puis ferme', () => {
  ecouterFlux(1, rappels)
  const s = FauxEventSource.derniere
  s.emettre('erreur', { message: 'boum' })
  expect(rappels.erreur).toHaveBeenCalledWith('boum')
  expect(s.close).toHaveBeenCalled()
})

it('le désabonnement ferme la source', () => {
  const stop = ecouterFlux(1, rappels)
  stop()
  expect(FauxEventSource.derniere.close).toHaveBeenCalled()
})

it('onerror avec connexion fermée : erreur("connexion perdue") une fois', () => {
  ecouterFlux(1, rappels)
  const s = FauxEventSource.derniere
  s.readyState = 2
  s.onerror!()
  s.onerror!()
  expect(rappels.erreur).toHaveBeenCalledOnce()
  expect(rappels.erreur).toHaveBeenCalledWith('connexion perdue')
})
