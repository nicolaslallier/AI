export interface Projet {
  id: number
  nom: string
  description: string
  depot_url: string | null
  branche_ref: string | null
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
  outil: string | null
  cree_le: string
}
export interface Document {
  id: number
  contenu: string
  etat: string
  maj_le: string
}
export interface Tache {
  id: number
  projet_id: number
  titre: string
  description: string
  criteres: string[]
  fichiers: string[]
  colonne: string
  rang: number
  origine: string
  document_id: number | null
  protegee: boolean
  verrou: number | null
  version: number
  cree_le: string
  maj_le: string
  depend_de: number[]
  dependances_non_terminees: number[]
}
export interface DonneesTache {
  titre: string
  description: string
  criteres: string[]
  fichiers: string[]
  depend_de: number[]
}
export interface Proposition {
  id: number
  pipeline_id: number
  etape_id: number
  projet_id: number
  sorte: 'nouvelle' | 'modification' | 'retrait'
  cle: string | null
  tache_id: number | null
  version_tache: number | null
  donnees: Record<string, unknown>
  etat: string
  tache_creee_id: number | null
  cree_le: string
}
export interface Kanban {
  taches: Tache[]
  propositions: Proposition[]
}
export interface KanbanToutAccepte extends Kanban {
  perimees: number
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
  sha: string | null
  produit: string | null
  messages: Message[]
  document: Document | null
  jauge: Jauge | null
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
  if (r.status === 204) return undefined as T
  return (await r.json()) as T
}

export const listerProjets = () => appel<Projet[]>('GET', '/projets')
export const creerProjet = (
  nom: string,
  description = '',
  depot_url: string | null = null,
  branche_ref: string | null = null,
) => appel<Projet>('POST', '/projets', { nom, description, depot_url, branche_ref })
export const modifierProjet = (
  id: number,
  champs: Partial<Pick<Projet, 'nom' | 'description' | 'depot_url' | 'branche_ref'>>,
) => appel<Projet>('PATCH', `/projets/${id}`, champs)
export const lireProjet = (id: number) => appel<ProjetDetail>('GET', `/projets/${id}`)

export const lireKanban = (projetId: number) => appel<Kanban>('GET', `/projets/${projetId}/kanban`)

export const creerTache = (projetId: number, d: DonneesTache) =>
  appel<Tache>('POST', `/projets/${projetId}/taches`, d)
export const modifierTache = (id: number, d: Partial<DonneesTache>) =>
  appel<Tache>('PATCH', `/taches/${id}`, d)
export const deplacerTache = (id: number, colonne: string, avant_id: number | null = null) =>
  appel<Tache>('POST', `/taches/${id}/deplacer`, { colonne, avant_id })
export const supprimerTache = (id: number) => appel<void>('DELETE', `/taches/${id}`)
export const annulerTache = (id: number) => appel<Tache>('POST', `/taches/${id}/annuler`)
export const accepterProposition = (id: number, donnees?: DonneesTache) =>
  appel<Kanban>('POST', `/propositions/${id}/accepter`, donnees ? { donnees } : {})
export const rejeterProposition = (id: number) => appel<Kanban>('POST', `/propositions/${id}/rejeter`)
export const toutAccepter = (etapeId: number) =>
  appel<KanbanToutAccepte>('POST', `/etapes/${etapeId}/propositions/tout-accepter`)

export const listerPipelines = (etat?: string) =>
  appel<PipelineResume[]>('GET', '/pipelines' + (etat ? `?etat=${encodeURIComponent(etat)}` : ''))
export const creerPipeline = (projet_id: number, type: string) =>
  appel<PipelineDetail>('POST', '/pipelines', { projet_id, type })
export const annulerPipeline = (id: number) =>
  appel<PipelineDetail>('POST', `/pipelines/${id}/annuler`)
export const lirePipeline = (id: number) => appel<PipelineDetail>('GET', `/pipelines/${id}`)

export const envoyerMessage = (etapeId: number, contenu: string) =>
  appel<object>('POST', `/etapes/${etapeId}/messages`, { contenu })
export const rediger = (etapeId: number) => appel<object>('POST', `/etapes/${etapeId}/rediger`)
export const reessayer = (etapeId: number) => appel<object>('POST', `/etapes/${etapeId}/reessayer`)
export const enregistrerDocument = (etapeId: number, contenu: string) =>
  appel<Document>('PUT', `/etapes/${etapeId}/document`, { contenu })
export const valider = (etapeId: number) =>
  appel<PipelineDetail>('POST', `/etapes/${etapeId}/valider`)
