import { afterEach, describe, expect, it, vi } from 'vitest'
import { demanderMusique } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('demanderMusique', () => {
  it('envoie le texte et renvoie la réponse', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ texte: 'ok' })))
    vi.stubGlobal('fetch', f)
    expect(await demanderMusique('salut')).toBe('ok')
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/musique')
    expect(JSON.parse(init.body as string)).toEqual({ texte: 'salut' })
  })

  it('remonte le détail du 502', async () => {
    vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ detail: 'injoignable' }), { status: 502 }))
    await expect(demanderMusique('x')).rejects.toThrow('injoignable')
  })
})
