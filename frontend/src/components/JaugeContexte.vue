<script setup lang="ts">
import type { Jauge } from '../api'
defineProps<{ jauge: Jauge; compacte?: boolean }>()
const couleurs = { ok: 'var(--succes)', alerte: 'var(--alerte)', plein: 'var(--danger)' }
</script>

<template>
  <div>
    <div class="barre">
      <div :style="{ width: Math.min(100, jauge.ratio * 100) + '%', background: couleurs[jauge.niveau] }"></div>
    </div>
    <small>Contexte : {{ jauge.utilises.toLocaleString('fr-FR') }} / {{ jauge.max.toLocaleString('fr-FR') }}</small>
    <p v-if="!compacte && jauge.niveau === 'alerte'" class="alerte">
      Le contexte se remplit : clique « Rédiger la spec » pour que l'agent reparte du brouillon.
    </p>
    <p v-if="!compacte && jauge.niveau === 'plein'" class="alerte">Contexte plein : rédige la spec pour continuer.</p>
  </div>
</template>

<style scoped>
.barre { height: 0.4rem; background: var(--gris-doux); border-radius: 999px; overflow: hidden; }
.barre div { height: 100%; }
.alerte { margin: 0.25rem 0; color: var(--alerte); }
</style>
