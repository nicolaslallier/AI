export function duree(debut: string, fin: string | null): string {
  if (fin === null) return 'en cours'
  const s = Math.max(0, Math.round((Date.parse(fin) - Date.parse(debut)) / 1000))
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`
}

export function numeroPr(url: string): string {
  const m = /\/pull\/(\d+)\/?$/.exec(url)
  return m ? `PR #${m[1]}` : 'PR'
}

// Un pr_url vient de la base : on ne le rend en lien que s'il pointe vers GitHub.
export const lienPrSur = (url: string | null): url is string => !!url && url.startsWith('https://github.com/')

export const extrait = (texte: string, max = 280): string => (texte.length > max ? `${texte.slice(0, max)}…` : texte)

export const emplacement = (c: { type: string; chemin: string | null; ligne: number | null }): string =>
  c.chemin ? (c.ligne ? `${c.chemin}:${c.ligne}` : c.chemin) : c.type === 'revue' ? 'revue' : 'conversation'
