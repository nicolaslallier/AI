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
const charge = ref(false)
const projets = ref<Projet[]>([])
const projetId = ref<number | ''>('')
const nouveauNom = ref('')
let minuteur: ReturnType<typeof setInterval> | undefined

async function charger() {
  try {
    pipelines.value = await listerPipelines(filtre.value || undefined)
    erreur.value = ''
    charge.value = true
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
  <div class="titre">
    <h1>Pipelines</h1>
    <select v-model="filtre" class="pousse" aria-label="Filtrer par état">
      <option value="">Tous les états</option>
      <option value="a_faire">À faire</option>
      <option value="en_cours">En cours</option>
      <option value="en_attente">En attente de toi</option>
      <option value="terminee">Terminé</option>
      <option value="echouee">Échoué</option>
    </select>
    <button class="primaire" @click="ouvrirFormulaire">+ Nouveau pipeline</button>
  </div>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <form v-if="formulaire" class="carte champs" @submit.prevent="creer">
    <label>
      Projet
      <select v-model="projetId">
        <option value="">Nouveau projet…</option>
        <option v-for="p in projets" :key="p.id" :value="p.id">{{ p.nom }}</option>
      </select>
    </label>
    <label v-if="projetId === ''">Nom du projet <input v-model="nouveauNom" required /></label>
    <div class="rangee">
      <button>Créer</button>
      <button type="button" @click="formulaire = false">Fermer</button>
    </div>
  </form>
  <div class="pile">
    <RouterLink v-for="p in pipelines" :key="p.id" :to="`/pipelines/${p.id}`" class="carte ligne">
      <strong>{{ p.projet_nom }}</strong>
      <span class="discret">{{ p.type }} n°{{ p.id }}</span>
      <EtatBadge :etat="p.etat" class="pousse" />
      <small>{{ new Date(p.maj_le).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) }}</small>
    </RouterLink>
    <p v-if="charge && !pipelines.length" class="vide">
      {{ filtre ? 'Aucun pipeline dans cet état.' : 'Aucun pipeline pour l\'instant. Crée-en un pour démarrer une spec.' }}
    </p>
  </div>
</template>
