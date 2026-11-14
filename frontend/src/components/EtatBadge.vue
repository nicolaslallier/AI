<script setup lang="ts">
const libelles: Record<string, string> = {
  a_faire: 'À faire',
  en_cours: 'En cours',
  en_attente: 'En attente de toi',
  terminee: 'Terminé',
  echouee: 'Échoué',
}
const couleurs: Record<string, string> = {
  a_faire: '#e5e7eb',
  en_cours: '#bfdbfe',
  en_attente: '#fde68a',
  terminee: '#bbf7d0',
  echouee: '#fecaca',
}
defineProps<{ etat: string }>()
</script>

<template>
  <span class="badge" :style="{ background: couleurs[etat] ?? '#e5e7eb' }">{{ libelles[etat] ?? etat }}</span>
</template>

<style scoped>
.badge { padding: 0.1rem 0.5rem; border-radius: 0.75rem; font-size: 0.85em; }
</style>
