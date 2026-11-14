<script setup lang="ts">
import type { Tache } from '../api'
import { COLONNES } from '../kanban'

const props = defineProps<{ tache: Tache }>()
const emit = defineEmits<{
  ouvrir: [Tache]
  annuler: [Tache]
  deplacer: [Tache, string]
  glisser: [Tache | null]
}>()

function choisir(e: Event) {
  const sel = e.target as HTMLSelectElement
  if (sel.value) emit('deplacer', props.tache, sel.value)
  sel.value = ''
}
</script>

<template>
  <article
    class="carte"
    :data-id="tache.id"
    :draggable="tache.verrou === null"
    @dragstart="(e) => { e.dataTransfer?.setData('text/plain', String(tache.id)); emit('glisser', tache) }"
    @dragend="emit('glisser', null)"
  >
    <strong>#{{ tache.id }} {{ tache.titre }}</strong>
    <div>
      <span v-if="tache.verrou !== null" class="badge">🔒 verrouillée (pipeline {{ tache.verrou }})</span>
      <span v-if="tache.protegee" class="badge">✋ protégée</span>
    </div>
    <div v-for="d in tache.dependances_non_terminees" :key="d" class="dep">⚠ dépend de #{{ d }} non terminée</div>
    <div class="actions">
      <template v-if="tache.verrou !== null">
        <button @click="emit('annuler', tache)">Annuler</button>
      </template>
      <template v-else>
        <button @click="emit('ouvrir', tache)">Modifier</button>
        <select aria-label="Déplacer vers…" @change="choisir">
          <option value="">Déplacer vers…</option>
          <option v-for="c in COLONNES.filter((c) => c.valeur !== tache.colonne)" :key="c.valeur" :value="c.valeur">
            {{ c.libelle }}
          </option>
        </select>
      </template>
    </div>
  </article>
</template>

<style scoped>
.carte { background: #fff; border: 1px solid #d1d5db; border-radius: 0.4rem; padding: 0.4rem; margin-bottom: 0.4rem; }
.carte[draggable='true'] { cursor: grab; }
.badge { font-size: 0.8em; background: #f3f4f6; border-radius: 0.5rem; padding: 0 0.4rem; margin-right: 0.25rem; }
.dep { color: #b45309; font-size: 0.85em; }
.actions { margin-top: 0.3rem; display: flex; gap: 0.3rem; }
</style>
