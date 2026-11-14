<script setup lang="ts">
import { ref } from 'vue'
import type { Etape } from '../api'
import { rendreMarkdown } from '../markdown'
import JaugeContexte from './JaugeContexte.vue'

const props = defineProps<{
  etape: Etape
  partiel?: string
  message?: string
  outils?: string[]
  propositions?: number
  projetId?: number
}>()
const emit = defineEmits<{ envoyer: [contenu: string, vider: () => void]; rediger: []; reessayer: [] }>()
const saisie = ref('')

function envoyer() {
  const t = saisie.value.trim()
  if (!t || props.etape.etat !== 'en_attente' || props.etape.jauge?.niveau === 'plein') return
  emit('envoyer', t, () => (saisie.value = ''))
}

function surEntree(e: KeyboardEvent) {
  if (e.isComposing) return
  e.preventDefault()
  envoyer()
}
</script>

<template>
  <section v-if="etape.produit === 'taches'">
    <p>
      {{ propositions ?? 0 }} propositions à traiter
      <RouterLink :to="`/projets/${projetId}/kanban`">Ouvrir le kanban</RouterLink>
    </p>
    <p v-if="etape.etat === 'echouee'" class="erreur">
      {{ etape.erreur }} <button v-if="etape.erreur !== 'annulé'" @click="emit('reessayer')">Réessayer</button>
    </p>
    <p v-if="message" class="erreur">{{ message }}</p>
  </section>
  <section v-else>
    <JaugeContexte v-if="etape.jauge" :jauge="etape.jauge" />
    <div class="messages">
      <div v-for="m in etape.messages" :key="m.id" :class="['bulle', m.role === 'user' ? 'moi' : 'agent', { systeme: m.role === 'system' }]">
        <details v-if="m.role === 'tool'"><summary>🔎 {{ m.outil }}</summary><pre>{{ m.contenu }}</pre></details>
        <em v-else-if="m.role === 'system'">{{ m.contenu }}</em>
        <template v-else-if="m.role === 'user'">{{ m.contenu }}</template>
        <div v-else v-html="rendreMarkdown(m.contenu)"></div>
      </div>
      <div v-if="etape.etat === 'en_cours'" class="bulle agent">
        <div v-if="partiel" v-html="rendreMarkdown(partiel)"></div>
        <em v-else>…</em>
        <div v-for="(o, i) in outils" :key="i" class="outil">🔎 {{ o }}</div>
      </div>
    </div>
    <p v-if="etape.etat === 'echouee'" class="erreur">
      {{ etape.erreur }} <button v-if="etape.erreur !== 'annulé'" @click="emit('reessayer')">Réessayer</button>
    </p>
    <p v-if="message" class="erreur">{{ message }}</p>
    <textarea
      v-model="saisie"
      rows="3"
      placeholder="Écris ton message…"
      :disabled="etape.etat !== 'en_attente' || etape.jauge?.niveau === 'plein'"
      @keydown.enter.exact="surEntree"
    ></textarea>
    <button :disabled="etape.etat !== 'en_attente'" @click="emit('rediger')">
      Rédiger {{ etape.produit === 'plan' ? 'le plan' : 'la spec' }}
    </button>
  </section>
</template>

<style scoped>
.messages { display: flex; flex-direction: column; gap: 0.5rem; margin: 0.5rem 0; }
.bulle { max-width: 80%; padding: 0.4rem 0.75rem; border-radius: 0.75rem; }
.bulle :deep(p) { margin: 0.25rem 0; }
.moi { align-self: flex-end; background: #dbeafe; white-space: pre-wrap; }
.systeme { color: #6b7280; }
.outil { color: #6b7280; font-size: 0.85em; }
.agent { align-self: flex-start; background: #f3f4f6; }
textarea { width: 100%; box-sizing: border-box; }
.erreur { color: #b91c1c; }
</style>
