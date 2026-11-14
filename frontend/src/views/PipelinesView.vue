<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  creerPipeline,
  creerProjet,
  listerPipelines,
  listerProjets,
  type PipelineResume,
  type Projet,
} from '../api'
import EtatBadge from '../components/EtatBadge.vue'

const router = useRouter()
const pipelines = ref<PipelineResume[]>([])
const filtre = ref('')
const erreur = ref('')
const formulaire = ref(false)
const projets = ref<Projet[]>([])
const projetId = ref<number | ''>('')
const nouveauNom = ref('')
let minuteur: ReturnType<typeof setInterval> | undefined

async function charger() {
  try {
    pipelines.value = await listerPipelines(filtre.value || undefined)
    erreur.value = ''
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

async function ouvrirFormulaire() {
  formulaire.value = true
  try {
    projets.value = await listerProjets()
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

async function creer() {
  try {
    let id = projetId.value
    if (id === '') id = (await creerProjet(nouveauNom.value.trim())).id
    const p = await creerPipeline(id, 'spec')
    router.push(`/pipelines/${p.id}`)
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

watch(filtre, charger)
onMounted(() => {
  charger()
  minuteur = setInterval(charger, 5000)
})
onUnmounted(() => clearInterval(minuteur))
</script>

<template>
  <h1>Pipelines</h1>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <div>
    <select v-model="filtre">
      <option value="">Tous les états</option>
      <option value="a_faire">À faire</option>
      <option value="en_cours">En cours</option>
      <option value="en_attente">En attente de toi</option>
      <option value="terminee">Terminé</option>
      <option value="echouee">Échoué</option>
    </select>
    <button @click="ouvrirFormulaire">Nouveau pipeline</button>
  </div>
  <form v-if="formulaire" @submit.prevent="creer">
    <select v-model="projetId">
      <option value="">Nouveau projet…</option>
      <option v-for="p in projets" :key="p.id" :value="p.id">{{ p.nom }}</option>
    </select>
    <input v-if="projetId === ''" v-model="nouveauNom" placeholder="Nom du projet" required />
    <button>Créer</button>
  </form>
  <table>
    <thead>
      <tr><th>Projet</th><th>Type</th><th>État</th><th>Mis à jour</th></tr>
    </thead>
    <tbody>
      <tr v-for="p in pipelines" :key="p.id">
        <td><RouterLink :to="`/pipelines/${p.id}`">{{ p.projet_nom }}</RouterLink></td>
        <td>{{ p.type }}</td>
        <td><EtatBadge :etat="p.etat" /></td>
        <td>{{ new Date(p.maj_le).toLocaleString('fr-FR') }}</td>
      </tr>
    </tbody>
  </table>
</template>
