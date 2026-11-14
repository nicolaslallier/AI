<script setup lang="ts">
import type { Jauge } from '../api'
defineProps<{ jauge: Jauge }>()
const couleurs = { ok: '#86efac', alerte: '#fcd34d', plein: '#fca5a5' }
</script>

<template>
  <div>
    <div class="barre">
      <div :style="{ width: Math.min(100, jauge.ratio * 100) + '%', background: couleurs[jauge.niveau] }"></div>
    </div>
    <small>{{ jauge.utilises }} / {{ jauge.max }}</small>
    <p v-if="jauge.niveau === 'alerte'" class="alerte">
      Le contexte se remplit : clique « Rédiger la spec » pour que l'agent reparte du brouillon.
    </p>
    <p v-if="jauge.niveau === 'plein'" class="alerte">Contexte plein : rédige la spec pour continuer.</p>
  </div>
</template>

<style scoped>
.barre { height: 0.5rem; background: #e5e7eb; border-radius: 0.25rem; overflow: hidden; }
.barre div { height: 100%; }
.alerte { margin: 0.25rem 0; }
</style>
