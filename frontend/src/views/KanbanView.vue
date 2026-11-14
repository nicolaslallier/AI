<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  accepterProposition, annulerTache, creerTache, deplacerTache, lireKanban, modifierTache, rejeterProposition,
  supprimerTache, toutAccepter, type DonneesTache, type Kanban, type Proposition, type Tache,
} from '../api'
import { COLONNES, filtrer, grouperParColonne } from '../kanban'
import CarteTache from '../components/CarteTache.vue'
import EditionTache from '../components/EditionTache.vue'
import PanneauPropositions from '../components/PanneauPropositions.vue'

const props = defineProps<{ id: string }>()
const projetId = Number(props.id)
const kanban = ref<Kanban>({ taches: [], propositions: [] })
const texte = ref('')
const erreur = ref('')
const perimees = ref<number | null>(null)
const glissee = ref<Tache | null>(null)
const edition = ref<{ tache?: Tache; proposition?: Proposition } | null>(null)
const erreurModale = ref('')
let minuteur: ReturnType<typeof setInterval> | undefined

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
const initiale = (p: Proposition) => ({
  titre: String(p.donnees.titre ?? ''),
  description: String(p.donnees.description ?? ''),
  criteres: (p.donnees.criteres as string[]) ?? [],
  fichiers: (p.donnees.fichiers as string[]) ?? [],
  depend_de: p.tache_id ? (cibleDe(p)?.depend_de ?? []) : [],
})
const cibleDe = (p: Proposition) => kanban.value.taches.find((t) => t.id === p.tache_id)

onMounted(() => {
  charger()
  minuteur = setInterval(charger, 5000)
})
onBeforeUnmount(() => clearInterval(minuteur))
</script>

<template>
  <h1>Kanban</h1>
  <p><RouterLink :to="`/projets/${projetId}`">← Projet</RouterLink></p>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <div class="barre">
    <input v-model="texte" placeholder="Filtrer…" aria-label="Filtrer les tâches" />
    <button @click="((erreurModale = ''), (edition = {}))">Nouvelle tâche</button>
  </div>
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
      <h3>{{ c.libelle }} ({{ colonnes[c.valeur].length }})</h3>
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
.barre { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }
.colonnes { display: grid; grid-template-columns: repeat(6, minmax(10rem, 1fr)); gap: 0.5rem; overflow-x: auto; }
.colonne { background: #f3f4f6; border-radius: 0.5rem; padding: 0.4rem; min-height: 8rem; }
</style>
