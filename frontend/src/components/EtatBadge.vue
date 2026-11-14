<script setup lang="ts">
const libelles: Record<string, string> = {
  a_faire: 'À faire',
  en_cours: 'En cours',
  en_attente: 'En attente de toi',
  terminee: 'Terminé',
  echouee: 'Échoué',
}
defineProps<{ etat: string }>()
</script>

<template>
  <span :class="['badge', etat]">{{ libelles[etat] ?? etat }}</span>
</template>
