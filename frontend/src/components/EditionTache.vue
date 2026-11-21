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
const doc = ref(src.doc ?? false)
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
    doc: doc.value,
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
      <div v-if="description" class="apercu markdown" v-html="apercu" />
      <label>Critères (un par ligne) <textarea v-model="criteres" rows="3" /></label>
      <label>Fichiers (un par ligne) <textarea v-model="fichiers" rows="3" /></label>
      <label class="dep">
        <input v-model="doc" type="checkbox" /> Documentation seulement (l'agent de doc, puis la PR)
      </label>
      <fieldset v-if="autres.length">
        <legend>Dépend de</legend>
        <label v-for="a in autres" :key="a.id" class="dep">
          <input v-model="dependances" type="checkbox" :value="a.id" /> #{{ a.id }} {{ a.titre }}
        </label>
      </fieldset>
      <div class="actions">
        <button type="submit">{{ libelle ?? 'Enregistrer' }}</button>
        <button type="button" @click="emit('fermer')">Fermer</button>
        <button v-if="tache" type="button" class="danger pousse" @click="supprimer">Supprimer</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.fond { position: fixed; inset: 0; background: #0008; display: flex; align-items: center; justify-content: center; z-index: 10; }
.modale { background: var(--surface); padding: 1.25rem; border-radius: var(--rayon); width: min(40rem, 95vw); max-height: 90vh; overflow: auto; display: flex; flex-direction: column; gap: 0.75rem; box-sizing: border-box; }
.dep { flex-direction: row; align-items: center; gap: 0.4rem; color: var(--texte); font-weight: 400; }
.apercu { border: 1px dashed var(--bord); border-radius: 0.55rem; padding: 0.5rem 0.75rem; }
.actions { display: flex; gap: 0.5rem; }
</style>
