<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { creerProjet, listerProjets, type Projet } from '../api'

const projets = ref<Projet[]>([])
const nom = ref('')
const description = ref('')
const depot = ref('')
const branche = ref('')
const erreur = ref('')
const charge = ref(false)

async function charger() {
  try {
    projets.value = await listerProjets()
    charge.value = true
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
  <div v-if="projets.length" class="grille">
    <article v-for="p in projets" :key="p.id" class="carte pile">
      <h2><RouterLink :to="`/projets/${p.id}`">{{ p.nom }}</RouterLink></h2>
      <p class="discret">{{ p.description || 'Pas de description.' }}</p>
      <div class="rangee">
        <RouterLink :to="`/projets/${p.id}`" class="bouton">Ouvrir</RouterLink>
        <RouterLink :to="`/projets/${p.id}/kanban`" class="bouton">Kanban</RouterLink>
      </div>
    </article>
  </div>
  <p v-else-if="charge" class="vide">Aucun projet pour l'instant. Crée le premier juste en dessous.</p>
  <section class="carte pile">
    <h2>Nouveau projet</h2>
    <form class="champs" @submit.prevent="creer">
      <label>Nom <input v-model="nom" required /></label>
      <label>Description <input v-model="description" /></label>
      <label>Dépôt GitHub (URL) <input v-model="depot" placeholder="https://github.com/…" /></label>
      <label>Branche de référence <input v-model="branche" placeholder="branche par défaut" /></label>
      <button>Créer le projet</button>
    </form>
  </section>
</template>
