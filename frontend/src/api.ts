export interface Projet {
  id: number
  nom: string
  description: string
  cree_le: string
}
export interface PipelineResume {
  id: number
  projet_id: number
  projet_nom: string
  type: string
  etat: string
  maj_le: string
}
export interface SpecCourante {
  id: number
  contenu: string
  maj_le: string
}
export interface ProjetDetail extends Projet {
  pipelines: PipelineResume[]
  spec_courante: SpecCourante | null
}
export interface Message {
  id: number
  role: string
  contenu: string
  cree_le: string
}
export interface Document {
  id: number
  contenu: string
  etat: string
  maj_le: string
}
export interface Jauge {
  utilises: number
  max: number
  ratio: number
  niveau: 'ok' | 'alerte' | 'plein'
}
export interface Etape {
  id: number
  ordre: number
  agent: string
  etat: string
  erreur: string | null
  action: string | null
  messages: Message[]
  document: Document | null
  jauge: Jauge
}
export interface PipelineDetail {
  id: number
  projet: { id: number; nom: string }
  type: string
  etat: string
  maj_le: string
  etapes: Etape[]
}

export class ErreurApi extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

async function appel<T>(methode: string, chemin: string, corps?: unknown): Promise<T> {
  const r = await fetch('/api' + chemin, {
    method: methode,
    headers: corps === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: corps === undefined ? undefined : JSON.stringify(corps),
  })
  if (!r.ok) {
    let detail = r.statusText
    try {
      const d = (await r.json()).detail
      if (typeof d === 'string') detail = d
      else if (d !== undefined) detail = JSON.stringify(d)
    } catch {
      /* corps non JSON : on garde le statut */
    }
    throw new ErreurApi(r.status, detail)
  }
  return (await r.json()) as T
}

export const listerProjets = () => appel<Projet[]>('GET', '/projets')
export const creerProjet = (nom: string, description = '') =>
  appel<Projet>('POST', '/projets', { nom, description })
export const lireProjet = (id: number) => appel<ProjetDetail>('GET', `/projets/${id}`)

export const listerPipelines = (etat?: string) =>
  appel<PipelineResume[]>('GET', '/pipelines' + (etat ? `?etat=${encodeURIComponent(etat)}` : ''))
export const creerPipeline = (projet_id: number, type: string) =>
  appel<PipelineDetail>('POST', '/pipelines', { projet_id, type })
export const lirePipeline = (id: number) => appel<PipelineDetail>('GET', `/pipelines/${id}`)

export const envoyerMessage = (etapeId: number, contenu: string) =>
  appel<object>('POST', `/etapes/${etapeId}/messages`, { contenu })
export const rediger = (etapeId: number) => appel<object>('POST', `/etapes/${etapeId}/rediger`)
export const reessayer = (etapeId: number) => appel<object>('POST', `/etapes/${etapeId}/reessayer`)
export const enregistrerDocument = (etapeId: number, contenu: string) =>
  appel<Document>('PUT', `/etapes/${etapeId}/document`, { contenu })
export const valider = (etapeId: number) =>
  appel<PipelineDetail>('POST', `/etapes/${etapeId}/valider`)
