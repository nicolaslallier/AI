import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ecouterEvenements, regrouper } from './evenements'

class FauxEventSource {
  static derniere: FauxEventSource
  close = vi.fn()
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

beforeEach(() => {
  ;(globalThis as any).EventSource = FauxEventSource
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

it('kanban appelle kanban(projetId)', () => {
  const kanban = vi.fn()
  ecouterEvenements({ kanban })
  expect(FauxEventSource.derniere.url).toBe('/api/evenements')
  FauxEventSource.derniere.emettre('kanban', { projet_id: 3 })
  FauxEventSource.derniere.emettre('kanban', { projet_id: null })
  expect(kanban).toHaveBeenNthCalledWith(1, 3)
  expect(kanban).toHaveBeenNthCalledWith(2, null)
})

it('pipelines appelle pipelines()', () => {
  const pipelines = vi.fn()
  ecouterEvenements({ pipelines })
  FauxEventSource.derniere.emettre('pipelines')
  expect(pipelines).toHaveBeenCalledOnce()
})

it('la fonction rendue ferme la source', () => {
  ecouterEvenements({})()
  expect(FauxEventSource.derniere.close).toHaveBeenCalled()
})

it('regrouper : trois appels rapprochés, un seul', () => {
  vi.useFakeTimers()
  const f = vi.fn()
  const g = regrouper(f)
  g()
  g()
  g()
  vi.advanceTimersByTime(300)
  expect(f).toHaveBeenCalledOnce()
})
