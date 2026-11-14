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
    <strong><span class="discret">#{{ tache.id }}</span> {{ tache.titre }}</strong>
    <div>
      <span v-if="tache.verrou !== null" class="badge">🔒 pipeline {{ tache.verrou }}</span>
      <span v-if="tache.protegee" class="badge">✋ protégée</span>
    </div>
    <div v-for="d in tache.dependances_non_terminees" :key="d" class="dep">⚠ dépend de #{{ d }} non terminée</div>
    <div class="actions">
      <template v-if="tache.verrou !== null">
        <button class="danger" @click="emit('annuler', tache)">Annuler</button>
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
.carte { background: var(--surface); border: 1px solid var(--bord); border-radius: 0.55rem; padding: 0.6rem; box-shadow: var(--ombre); display: flex; flex-direction: column; gap: 0.35rem; }
.carte[draggable='true'] { cursor: grab; }
.carte[draggable='true']:hover { border-color: var(--accent); }
.badge { margin-right: 0.25rem; }
.dep { color: var(--alerte); font-size: 0.85em; }
.actions { display: flex; flex-wrap: wrap; gap: 0.3rem; font-size: 0.85rem; }
.actions select { flex: 1 1 8rem; }
</style>
