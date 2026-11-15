<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { lireAudit, type LigneAudit } from '../api'

const lignes = ref<LigneAudit[]>([])
const erreur = ref('')
const charge = ref(false)
const fini = ref(false)

async function charger() {
  try {
    const suite = await lireAudit(lignes.value.at(-1)?.id)
    lignes.value.push(...suite)
    fini.value = suite.length < 100
    charge.value = true
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

onMounted(charger)
</script>

<template>
  <h1>Audit</h1>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <table v-if="lignes.length">
    <thead>
      <tr><th>Quand</th><th>Auteur</th><th>Action</th><th>Objet</th></tr>
    </thead>
    <tbody>
      <tr v-for="l in lignes" :key="l.id">
        <td>{{ new Date(l.quand).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'medium' }) }}</td>
        <td>{{ l.auteur }}</td>
        <td>{{ l.action }}</td>
        <td>{{ l.objet }} n°{{ l.objet_id }}</td>
      </tr>
    </tbody>
  </table>
  <p v-else-if="charge" class="vide">Rien d'inscrit pour l'instant.</p>
  <button v-if="lignes.length && !fini" @click="charger">Plus anciens</button>
</template>
