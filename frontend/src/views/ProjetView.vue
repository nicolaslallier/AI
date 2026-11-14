<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { creerPipeline, lireProjet, modifierProjet, type ProjetDetail } from '../api'
import { rendreMarkdown } from '../markdown'
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

async function planifier() {
  if (enCours.value) return
  enCours.value = true
  erreur.value = ''
  try {
    const p = await creerPipeline(Number(props.id), 'planification')
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
    <h1>{{ projet.nom }}</h1>
    <p>{{ projet.description }}</p>
    <p><RouterLink :to="`/projets/${projet.id}/kanban`">Kanban</RouterLink></p>
    <form @submit.prevent="enregistrer">
      <input v-model="depot" placeholder="Dépôt GitHub (URL)" />
      <input v-model="branche" placeholder="Branche de référence (vide = branche par défaut)" />
      <button>Enregistrer le dépôt</button>
    </form>
    <button :disabled="!projet.spec_courante || enCours" @click="planifier">Lancer la planification</button>
    <h2>Pipelines</h2>
    <p v-if="!projet.pipelines.length">Aucun pipeline.</p>
    <ul>
      <li v-for="p in projet.pipelines" :key="p.id">
        <RouterLink :to="`/pipelines/${p.id}`">{{ p.type }} n°{{ p.id }}</RouterLink>
        <EtatBadge :etat="p.etat" />
      </li>
    </ul>
    <h2>Spec courante</h2>
    <div v-if="spec" v-html="spec"></div>
    <p v-else>Pas encore de spec validée.</p>
  </template>
</template>
