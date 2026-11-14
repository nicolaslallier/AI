<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { creerProjet, listerProjets, type Projet } from '../api'

const projets = ref<Projet[]>([])
const nom = ref('')
const description = ref('')
const depot = ref('')
const branche = ref('')
const erreur = ref('')

async function charger() {
  try {
    projets.value = await listerProjets()
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

async function creer() {
  try {
    await creerProjet(nom.value, description.value, depot.value.trim() || null, branche.value.trim() || null)
    nom.value = description.value = depot.value = branche.value = erreur.value = ''
    await charger()
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

onMounted(charger)
</script>

<template>
  <h1>Projets</h1>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <ul>
    <li v-for="p in projets" :key="p.id">
      <RouterLink :to="`/projets/${p.id}`">{{ p.nom }}</RouterLink>
      <RouterLink :to="`/projets/${p.id}/kanban`"> (Kanban)</RouterLink>
      <span v-if="p.description"> : {{ p.description }}</span>
    </li>
  </ul>
  <form @submit.prevent="creer">
    <input v-model="nom" placeholder="Nom du projet" required />
    <input v-model="description" placeholder="Description" />
    <input v-model="depot" placeholder="Dépôt GitHub (URL)" />
    <input v-model="branche" placeholder="Branche de référence (vide = branche par défaut)" />
    <button>Créer le projet</button>
  </form>
</template>
