import { afterEach, describe, expect, it, vi } from 'vitest'
import { demanderMusique } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('demanderMusique', () => {
  it('envoie le texte et le context_id, renvoie la réponse', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ texte: 'ok', context_id: 'c2' })))
    vi.stubGlobal('fetch', f)
    expect(await demanderMusique('salut', 'c1')).toEqual({ texte: 'ok', context_id: 'c2' })
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/musique')
    expect(JSON.parse(init.body as string)).toEqual({ texte: 'salut', context_id: 'c1' })
  })

  it('remonte le détail du 502', async () => {
    vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ detail: 'injoignable' }), { status: 502 }))
    await expect(demanderMusique('x', null)).rejects.toThrow('injoignable')
  })
})
