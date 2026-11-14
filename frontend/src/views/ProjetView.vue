<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { lireProjet, type ProjetDetail } from '../api'
import { rendreMarkdown } from '../markdown'
import EtatBadge from '../components/EtatBadge.vue'

const props = defineProps<{ id: string }>()
const projet = ref<ProjetDetail | null>(null)
const erreur = ref('')
const spec = computed(() =>
  projet.value?.spec_courante ? rendreMarkdown(projet.value.spec_courante.contenu) : '',
)

onMounted(async () => {
  try {
    projet.value = await lireProjet(Number(props.id))
  } catch (e) {
    erreur.value = (e as Error).message
  }
})
</script>

<template>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <template v-if="projet">
    <h1>{{ projet.nom }}</h1>
    <p>{{ projet.description }}</p>
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
