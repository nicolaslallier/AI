<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { creerPipeline, lireProjet, modifierProjet, type ProjetDetail } from '../api'
import { rendreMarkdown } from '../markdown'
import ConfigExecution from '../components/ConfigExecution.vue'
import EtatBadge from '../components/EtatBadge.vue'

const props = defineProps<{ id: string }>()
const projet = ref<ProjetDetail | null>(null)
const erreur = ref('')
const spec = computed(() =>
  projet.value?.spec_courante ? rendreMarkdown(projet.value.spec_courante.contenu) : '',
)

const router = useRouter()
const depot = ref('')
const branche = ref('')
const enCours = ref(false)

async function charger() {
  try {
    projet.value = await lireProjet(Number(props.id))
    depot.value = projet.value.depot_url ?? ''
    branche.value = projet.value.branche_ref ?? ''
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

async function enregistrer() {
  erreur.value = ''
  try {
    await modifierProjet(Number(props.id), {
      depot_url: depot.value.trim() || null,
      branche_ref: branche.value.trim() || null,
    })
    await charger()
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

async function lancer(type: string) {
  if (enCours.value) return
  enCours.value = true
  erreur.value = ''
  try {
    const p = await creerPipeline(Number(props.id), type)
    router.push(`/pipelines/${p.id}`)
  } catch (e) {
    erreur.value = (e as Error).message // un 409 porte déjà son detail en français
  } finally {
    enCours.value = false
  }
}

onMounted(charger)
</script>

<template>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <template v-if="projet">
    <div class="titre">
      <h1>{{ projet.nom }}</h1>
      <RouterLink :to="`/projets/${projet.id}/kanban`" class="bouton pousse">Kanban</RouterLink>
      <button class="primaire" :disabled="!projet.spec_courante || enCours" @click="lancer('planification')">
        Lancer la planification
      </button>
      <button class="primaire" :disabled="enCours" @click="lancer('architecture')">Lancer l'architecture</button>
    </div>
    <p v-if="projet.description" class="discret">{{ projet.description }}</p>
    <p v-if="!projet.spec_courante" class="discret">La planification se débloque dès qu'une spec est validée.</p>
    <section class="carte pile">
      <h2>Dépôt</h2>
      <form class="champs" @submit.prevent="enregistrer">
        <label>Dépôt GitHub (URL) <input v-model="depot" placeholder="https://github.com/…" /></label>
        <label>Branche de référence <input v-model="branche" placeholder="branche par défaut" /></label>
        <button>Enregistrer le dépôt</button>
      </form>
    </section>
    <section class="carte pile">
      <h2>Exécution</h2>
      <ConfigExecution :projet-id="projet.id" :config="projet.config_execution" @enregistre="charger" />
    </section>
    <h2>Pipelines</h2>
    <div class="pile">
      <RouterLink v-for="p in projet.pipelines" :key="p.id" :to="`/pipelines/${p.id}`" class="carte ligne">
        <strong>{{ p.type }} n°{{ p.id }}</strong>
        <EtatBadge :etat="p.etat" class="pousse" />
      </RouterLink>
      <p v-if="!projet.pipelines.length" class="vide">Aucun pipeline pour ce projet.</p>
    </div>
    <h2>Spec courante</h2>
    <div v-if="spec" class="carte markdown" v-html="spec"></div>
    <p v-else class="vide">Pas encore de spec validée.</p>
  </template>
</template>
