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
  config_execution: string | null
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
export interface Avis {
  id: number
  agent: string
  contenu: string
  etat: string
  version: number
  ancienne: boolean
}
export interface Document {
  id: number
  contenu: string
  etat: string
  version: number
  maj_le: string
  avis: Avis[]
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
  pr_url: string | null
  resume_blocage: string | null
  reprise: boolean
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
  config_execution: boolean
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
  modele: string | null
  modele_fige: boolean
  modeles: string[]
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
  execution: { branche: string; phase: string; renvois: number; pr_url: string | null; mode: string; notes: { agent: string; texte: string }[] } | null
  commandes: Commande[]
  commentaires: CommentairePris[]
}
export interface CommentairePris {
  id: number
  type: string
  auteur: string
  texte: string
  url: string
  chemin: string | null
  ligne: number | null
  tri: string | null
  consigne: string | null
  repondu_le: string | null
}
export interface Commande {
  etape_id: number
  nom: string
  code: number | null
  delai_depasse: boolean
  sortie: string
  debut: string
  fin: string
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

export const definirExecution = (id: number, yaml: string) =>
  appel<Projet>('PUT', `/projets/${id}/execution`, { yaml })

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

export interface LigneAudit {
  id: number
  quand: string
  auteur: string
  action: string
  objet: string
  objet_id: number
}
export const lireAudit = (avant?: number) =>
  appel<LigneAudit[]>('GET', '/audit' + (avant ? `?avant=${avant}` : ''))

export const listerPipelines = (etat?: string) =>
  appel<PipelineResume[]>('GET', '/pipelines' + (etat ? `?etat=${encodeURIComponent(etat)}` : ''))
export const creerPipeline = (projet_id: number, type: string) =>
  appel<PipelineDetail>('POST', '/pipelines', { projet_id, type })
export const annulerPipeline = (id: number) =>
  appel<PipelineDetail>('POST', `/pipelines/${id}/annuler`)
export const lirePipeline = (id: number) => appel<PipelineDetail>('GET', `/pipelines/${id}`)

export const envoyerMessage = (etapeId: number, contenu: string, modele?: string) =>
  appel<object>('POST', `/etapes/${etapeId}/messages`, { contenu, modele })
export const rediger = (etapeId: number) => appel<object>('POST', `/etapes/${etapeId}/rediger`)
export const reessayer = (etapeId: number) => appel<object>('POST', `/etapes/${etapeId}/reessayer`)
export const enregistrerDocument = (etapeId: number, contenu: string) =>
  appel<Document>('PUT', `/etapes/${etapeId}/document`, { contenu })
export const demanderAvis = (documentId: number) => appel<void>('POST', `/documents/${documentId}/avis`)
export const changerEtatAvis = (id: number, etat: 'pris_en_compte' | 'ecarte' | 'ouvert') =>
  appel<Avis>('PATCH', `/avis/${id}`, { etat })
export const valider = (etapeId: number) =>
  appel<PipelineDetail>('POST', `/etapes/${etapeId}/valider`)

export interface ConversationResume {
  id: number
  agent: string
  titre: string
  etat: string
  maj_le: string
}
export interface ConversationDetail {
  id: number
  agent: string
  titre: string
  etat: 'pret' | 'en_cours' | 'erreur'
  erreur: string | null
  messages: Message[]
  jauge: Jauge | null
  actions: ActionConversation[]
}
export const listerConversations = () => appel<ConversationResume[]>('GET', '/conversations')
export const creerConversation = (agent = 'orchestrateur') =>
  appel<ConversationDetail>('POST', '/conversations', { agent })
export const lireConversation = (id: number) => appel<ConversationDetail>('GET', `/conversations/${id}`)
export const renommerConversation = (id: number, titre: string) =>
  appel<ConversationDetail>('PATCH', `/conversations/${id}`, { titre })
export const supprimerConversation = (id: number) => appel<void>('DELETE', `/conversations/${id}`)
export const envoyerMessageConversation = (id: number, contenu: string) =>
  appel<object>('POST', `/conversations/${id}/messages`, { contenu })
export const reessayerConversation = (id: number) => appel<object>('POST', `/conversations/${id}/reessayer`)

export interface ActionConversation {
  id: number
  nom: string
  parametres: Record<string, unknown>
  etat: 'proposee' | 'confirmee' | 'refusee' | 'echouee' | 'perimee'
  resultat: string | null
  lien: string | null
  cree_le: string
}
export const confirmerAction = (id: number) => appel<object>('POST', `/actions/${id}/confirmer`)
export const refuserAction = (id: number) => appel<object>('POST', `/actions/${id}/refuser`)

export type EtatPoste = 'libre' | 'au_travail' | 'en_attente' | 'en_erreur'
export interface Travail {
  sorte: 'etape' | 'conversation' | 'avis'
  etat: Exclude<EtatPoste, 'libre'>
  libelle: string
  lien: string
  tour: number | null
  jauge: Jauge | null
}
export interface Poste {
  nom: string
  etat: EtatPoste
  travaux: Travail[]
  appels_jour: number
  jetons_jour: number
  conteneur: { repond: boolean; version: string | null } | null
}
export interface Groupe {
  nom: string | null
  agents: string[]
}
export interface Bureau {
  groupes: Groupe[]
  postes: Record<string, Poste>
}
export interface MissionAgent {
  mission: string
  debut: string
  duree_ms: number
  appels: number
  jetons_entree: number
  jetons_sortie: number
  issue: string
  libelle: string | null
  lien: string | null
}
export interface PosteDetail {
  nom: string
  description: string
  modele: string
  modele_si_meme: string | null
  outils: string[]
  tours_max: number
  contexte_max: number
  missions: MissionAgent[]
}
export const lireBureau = () => appel<Bureau>('GET', '/bureau')
export const lirePoste = (nom: string) =>
  appel<PosteDetail>('GET', `/bureau/${encodeURIComponent(nom)}`)
