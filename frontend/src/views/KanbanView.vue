<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  accepterProposition, annulerTache, creerTache, deplacerTache, lireKanban, modifierTache, rejeterProposition,
  supprimerTache, toutAccepter, type DonneesTache, type Kanban, type Proposition, type Tache,
} from '../api'
import { ecouterEvenements, regrouper } from '../evenements'
import { COLONNES, filtrer, grouperParColonne } from '../kanban'
import CarteTache from '../components/CarteTache.vue'
import EditionTache from '../components/EditionTache.vue'
import PanneauPropositions from '../components/PanneauPropositions.vue'

const props = defineProps<{ id: string }>()
const projetId = Number(props.id)
const kanban = ref<Kanban>({ config_execution: true, taches: [], propositions: [] })
const texte = ref('')
const erreur = ref('')
const perimees = ref<number | null>(null)
const glissee = ref<Tache | null>(null)
const edition = ref<{ tache?: Tache; proposition?: Proposition } | null>(null)
const erreurModale = ref('')
let minuteur: ReturnType<typeof setInterval> | undefined
let arreter: (() => void) | undefined

const colonnes = computed(() => grouperParColonne(filtrer(kanban.value.taches, texte.value)))

async function charger() {
  if (glissee.value) return // sondage suspendu pendant un glissement
  try {
    kanban.value = await lireKanban(projetId)
  } catch (e) {
    erreur.value = (e as Error).message
  }
}
async function agir(f: () => Promise<unknown>) {
  erreur.value = ''
  try {
    await f()
  } catch (e) {
    erreur.value = (e as Error).message
  }
  glissee.value = null
  await charger()
}
const deplacer = (t: Tache, colonne: string, avant: number | null = null) =>
  agir(() => deplacerTache(t.id, colonne, avant))

function deposer(colonne: string, avant: number | null, e: DragEvent) {
  e.preventDefault()
  const t = glissee.value
  if (!t || avant === t.id) return (glissee.value = null)
  deplacer(t, colonne, avant)
}
// carte survolée : on insère avant elle ; hors carte : en fin de colonne
const surCarte = (colonne: string, e: DragEvent) => {
  const carte = (e.target as HTMLElement).closest<HTMLElement>('[data-id]')
  deposer(colonne, carte ? Number(carte.dataset.id) : null, e)
}

async function enregistrer(d: DonneesTache) {
  const { tache, proposition } = edition.value!
  erreurModale.value = ''
  try {
    if (proposition) kanban.value = await accepterProposition(proposition.id, d)
    else if (tache) await modifierTache(tache.id, d)
    else await creerTache(projetId, d)
    edition.value = null
    await charger()
  } catch (e) {
    erreurModale.value = (e as Error).message
  }
}
async function supprimer() {
  erreurModale.value = ''
  try {
    await supprimerTache(edition.value!.tache!.id)
    edition.value = null
    await charger()
  } catch (e) {
    erreurModale.value = (e as Error).message
  }
}
// une modification est partielle : les champs absents gardent la valeur de la tâche
const initiale = (p: Proposition) => ({
  titre: String(p.donnees.titre ?? cibleDe(p)?.titre ?? ''),
  description: String(p.donnees.description ?? cibleDe(p)?.description ?? ''),
  criteres: (p.donnees.criteres as string[]) ?? cibleDe(p)?.criteres ?? [],
  fichiers: (p.donnees.fichiers as string[]) ?? cibleDe(p)?.fichiers ?? [],
  depend_de: p.tache_id ? (cibleDe(p)?.depend_de ?? []) : [],
})
const cibleDe = (p: Proposition) => kanban.value.taches.find((t) => t.id === p.tache_id)

onMounted(() => {
  charger()
  minuteur = setInterval(charger, 60000) // filet de sécurité ; les événements font le reste
  const recharger = regrouper(charger)
  arreter = ecouterEvenements({ kanban: (id) => (id === null || id === projetId) && recharger() })
})
onBeforeUnmount(() => {
  clearInterval(minuteur)
  arreter?.()
})
</script>

<template>
  <div class="titre">
    <h1>Kanban</h1>
    <RouterLink :to="`/projets/${projetId}`">← Retour au projet</RouterLink>
    <input v-model="texte" class="pousse" type="search" placeholder="Filtrer…" aria-label="Filtrer les tâches" />
    <button class="primaire" @click="((erreurModale = ''), (edition = {}))">+ Nouvelle tâche</button>
  </div>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <p v-if="!kanban.config_execution" class="alerte">Sans config d'exécution, aucune tâche Prête ne démarre.</p>
  <PanneauPropositions
    v-if="kanban.propositions.length || perimees"
    :propositions="kanban.propositions"
    :taches="kanban.taches"
    :perimees="perimees"
    @accepter="(p) => agir(async () => (kanban = await accepterProposition(p.id)))"
    @rejeter="(p) => agir(async () => (kanban = await rejeterProposition(p.id)))"
    @modifier="(p) => ((erreurModale = ''), (edition = { proposition: p }))"
    @tout-accepter="(e) => agir(async () => { const k = await toutAccepter(e); kanban = k; perimees = k.perimees })"
  />
  <div class="colonnes">
    <section
      v-for="c in COLONNES"
      :key="c.valeur"
      class="colonne"
      @dragover.prevent
      @drop="surCarte(c.valeur, $event)"
    >
      <h3>{{ c.libelle }} <span class="badge">{{ colonnes[c.valeur].length }}</span></h3>
      <CarteTache
        v-for="t in colonnes[c.valeur]"
        :key="t.id"
        :tache="t"
        @ouvrir="(x) => ((erreurModale = ''), (edition = { tache: x }))"
        @annuler="(x) => agir(() => annulerTache(x.id))"
        @deplacer="(x, col) => deplacer(x, col)"
        @glisser="(x) => (glissee = x)"
      />
    </section>
  </div>
  <EditionTache
    v-if="edition"
    v-model:erreur="erreurModale"
    :tache="edition.tache"
    :initiale="edition.proposition ? initiale(edition.proposition) : undefined"
    :autres="kanban.taches.filter((t) => t.id !== edition!.tache?.id)"
    :libelle="edition.proposition ? 'Accepter' : edition.tache ? 'Enregistrer' : 'Créer'"
    @enregistrer="enregistrer"
    @supprimer="supprimer"
    @fermer="edition = null"
  />
</template>

<style scoped>
.colonnes { display: grid; grid-template-columns: repeat(6, minmax(10rem, 1fr)); gap: 0.75rem; overflow-x: auto; align-items: start; }
.colonne { background: var(--creux); border-radius: var(--rayon); padding: 0.6rem; min-height: 8rem; display: flex; flex-direction: column; gap: 0.5rem; }
.colonne h3 { display: flex; justify-content: space-between; align-items: center; padding: 0.1rem 0.25rem; }
</style>
