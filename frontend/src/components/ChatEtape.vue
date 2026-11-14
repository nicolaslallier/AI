<script setup lang="ts">
import { ref } from 'vue'
import type { Etape } from '../api'
import { rendreMarkdown } from '../markdown'
import JaugeContexte from './JaugeContexte.vue'

const props = defineProps<{ etape: Etape; partiel?: string; message?: string }>()
const emit = defineEmits<{ envoyer: [contenu: string, vider: () => void]; rediger: []; reessayer: [] }>()
const saisie = ref('')

function envoyer() {
  const t = saisie.value.trim()
  if (!t || props.etape.etat !== 'en_attente' || props.etape.jauge.niveau === 'plein') return
  emit('envoyer', t, () => (saisie.value = ''))
}

function surEntree(e: KeyboardEvent) {
  if (e.isComposing) return
  e.preventDefault()
  envoyer()
}
</script>

<template>
  <section>
    <JaugeContexte :jauge="etape.jauge" />
    <div class="messages">
      <div v-for="m in etape.messages" :key="m.id" :class="['bulle', m.role === 'user' ? 'moi' : 'agent']">
        <template v-if="m.role === 'user'">{{ m.contenu }}</template>
        <div v-else v-html="rendreMarkdown(m.contenu)"></div>
      </div>
      <div v-if="etape.etat === 'en_cours'" class="bulle agent">
        <div v-if="partiel" v-html="rendreMarkdown(partiel)"></div>
        <em v-else>…</em>
      </div>
    </div>
    <p v-if="etape.etat === 'echouee'" class="erreur">
      {{ etape.erreur }} <button @click="emit('reessayer')">Réessayer</button>
    </p>
    <p v-if="message" class="erreur">{{ message }}</p>
    <textarea
      v-model="saisie"
      rows="3"
      placeholder="Écris ton message…"
      :disabled="etape.etat !== 'en_attente' || etape.jauge.niveau === 'plein'"
      @keydown.enter.exact="surEntree"
    ></textarea>
    <button :disabled="etape.etat !== 'en_attente'" @click="emit('rediger')">Rédiger la spec</button>
  </section>
</template>

<style scoped>
.messages { display: flex; flex-direction: column; gap: 0.5rem; margin: 0.5rem 0; }
.bulle { max-width: 80%; padding: 0.4rem 0.75rem; border-radius: 0.75rem; white-space: pre-wrap; }
.bulle :deep(p) { margin: 0.25rem 0; }
.moi { align-self: flex-end; background: #dbeafe; }
.agent { align-self: flex-start; background: #f3f4f6; }
textarea { width: 100%; box-sizing: border-box; }
.erreur { color: #b91c1c; }
</style>
