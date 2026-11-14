<script setup lang="ts">
import { computed } from 'vue'
import type { ActionConversation } from '../api'
import { libelleAction } from '../conversations'
import { rendreMarkdown } from '../markdown'

const props = defineProps<{ action: ActionConversation; occupe: boolean }>()
defineEmits<{ (e: 'confirmer'): void; (e: 'refuser'): void }>()

const spec = computed(() => (props.action.nom === 'deposer_spec' ? String(props.action.parametres.contenu ?? '') : null))
const autres = computed(() => {
  const { contenu, ...reste } = props.action.parametres
  return props.action.nom === 'deposer_spec' ? reste : props.action.parametres
})
const ETATS = { refusee: 'refusée', perimee: 'périmée' } as const
</script>

<template>
  <div :class="['bulle', 'agent', 'action', { grise: action.etat === 'refusee' || action.etat === 'perimee' }]">
    <strong>{{ libelleAction(action) }}</strong>
    <pre>{{ JSON.stringify(autres, null, 2) }}</pre>
    <div v-if="spec !== null" class="markdown" v-html="rendreMarkdown(spec)"></div>
    <div v-if="action.etat === 'proposee'" class="rangee">
      <button :disabled="occupe" @click="$emit('confirmer')">Confirmer</button>
      <button class="danger" :disabled="occupe" @click="$emit('refuser')">Refuser</button>
    </div>
    <p v-else-if="action.etat === 'confirmee'">
      <template v-if="action.resultat === null">Confirmée, résultat inconnu</template>
      <template v-else>{{ action.resultat }}</template>
      <RouterLink v-if="action.lien" :to="action.lien"> Ouvrir</RouterLink>
    </p>
    <p v-else-if="action.etat === 'echouee'" class="erreur">{{ action.resultat }}</p>
    <em v-else class="discret">{{ ETATS[action.etat] }}</em>
  </div>
</template>

<style scoped>
.action { border: 1px solid var(--bleu-doux); max-width: 90%; }
.action pre { white-space: pre-wrap; margin: 0.3rem 0; }
.grise { opacity: 0.6; }
</style>
