<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DonneesTache, Tache } from '../api'
import { rendreMarkdown } from '../markdown'

// `tache` : édition d'une tâche existante ; `initiale` : pré-remplissage (proposition) ou vide.
const props = defineProps<{
  tache?: Tache
  initiale?: Partial<DonneesTache>
  autres: Tache[]
  libelle?: string
}>()
const emit = defineEmits<{ enregistrer: [DonneesTache]; supprimer: []; fermer: [] }>()
const src = props.tache ?? props.initiale ?? {}
const titre = ref(src.titre ?? '')
const description = ref(src.description ?? '')
const criteres = ref((src.criteres ?? []).join('\n'))
const fichiers = ref((src.fichiers ?? []).join('\n'))
const dependances = ref<number[]>([...(props.tache?.depend_de ?? props.initiale?.depend_de ?? [])])
const erreur = defineModel<string>('erreur', { default: '' })
const apercu = computed(() => rendreMarkdown(description.value))
const lignes = (s: string) => s.split('\n').map((l) => l.trim()).filter(Boolean)

function valider() {
  emit('enregistrer', {
    titre: titre.value,
    description: description.value,
    criteres: lignes(criteres.value),
    fichiers: lignes(fichiers.value),
    depend_de: dependances.value,
  })
}
function supprimer() {
  if (confirm('Supprimer cette tâche ?')) emit('supprimer')
}
</script>

<template>
  <div class="fond" @click.self="emit('fermer')">
    <form class="modale" @submit.prevent="valider">
      <h2>{{ tache ? `Tâche #${tache.id}` : 'Nouvelle tâche' }}</h2>
      <p v-if="erreur" class="erreur">{{ erreur }}</p>
      <label>Titre <input v-model="titre" required /></label>
      <label>Description (markdown) <textarea v-model="description" rows="5" /></label>
      <div v-if="description" class="apercu" v-html="apercu" />
      <label>Critères (un par ligne) <textarea v-model="criteres" rows="3" /></label>
      <label>Fichiers (un par ligne) <textarea v-model="fichiers" rows="3" /></label>
      <fieldset v-if="autres.length">
        <legend>Dépend de</legend>
        <label v-for="a in autres" :key="a.id" class="dep">
          <input v-model="dependances" type="checkbox" :value="a.id" /> #{{ a.id }} {{ a.titre }}
        </label>
      </fieldset>
      <div class="actions">
        <button type="submit">{{ libelle ?? 'Enregistrer' }}</button>
        <button type="button" @click="emit('fermer')">Fermer</button>
        <button v-if="tache" type="button" @click="supprimer">Supprimer</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.fond { position: fixed; inset: 0; background: #0006; display: flex; align-items: center; justify-content: center; z-index: 10; }
.modale { background: #fff; padding: 1rem; border-radius: 0.5rem; width: min(40rem, 95vw); max-height: 90vh; overflow: auto; display: flex; flex-direction: column; gap: 0.5rem; }
.modale label { display: flex; flex-direction: column; }
.dep { flex-direction: row !important; gap: 0.4rem; }
.apercu { border: 1px dashed #d1d5db; padding: 0.4rem; }
.actions { display: flex; gap: 0.5rem; }
</style>
