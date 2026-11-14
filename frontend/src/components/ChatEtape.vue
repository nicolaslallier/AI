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
  <section v-if="etape.produit === 'taches'" class="pile">
    <div class="rangee">
      <span><strong>{{ propositions ?? 0 }}</strong> proposition(s) à traiter</span>
      <RouterLink :to="`/projets/${projetId}/kanban`" class="bouton primaire">Ouvrir le kanban</RouterLink>
    </div>
    <p v-if="etape.etat === 'echouee'" class="erreur">
      {{ etape.erreur }} <button type="button" v-if="etape.erreur !== 'annulé'" @click="emit('reessayer')">Réessayer</button>
    </p>
    <p v-if="message" class="erreur">{{ message }}</p>
  </section>
  <section v-else class="pile">
    <JaugeContexte v-if="etape.jauge" :jauge="etape.jauge" />
    <div class="messages">
      <div v-for="m in etape.messages" :key="m.id" :class="['bulle', m.role === 'user' ? 'moi' : 'agent', { systeme: m.role === 'system' }]">
        <details v-if="m.role === 'tool'"><summary>🔎 {{ m.outil }}</summary><pre>{{ m.contenu }}</pre></details>
        <em v-else-if="m.role === 'system'">{{ m.contenu }}</em>
        <template v-else-if="m.role === 'user'">{{ m.contenu }}</template>
        <div v-else class="markdown" v-html="rendreMarkdown(m.contenu)"></div>
      </div>
      <div v-if="etape.etat === 'en_cours'" class="bulle agent">
        <div v-if="partiel" class="markdown" v-html="rendreMarkdown(partiel)"></div>
        <em v-else class="discret">L'agent réfléchit…</em>
        <div v-for="(o, i) in outils" :key="i" class="outil">🔎 {{ o }}</div>
      </div>
    </div>
    <p v-if="etape.etat === 'echouee'" class="erreur">
      {{ etape.erreur }} <button type="button" v-if="etape.erreur !== 'annulé'" @click="emit('reessayer')">Réessayer</button>
    </p>
    <p v-if="message" class="erreur">{{ message }}</p>
    <textarea
      v-model="saisie"
      rows="3"
      placeholder="Écris ton message… (Entrée pour envoyer, Maj+Entrée pour une nouvelle ligne)"
      :disabled="etape.etat !== 'en_attente' || etape.jauge?.niveau === 'plein'"
      @keydown.enter.exact="surEntree"
    ></textarea>
    <div class="rangee">
      <button :disabled="!saisie.trim() || etape.etat !== 'en_attente' || etape.jauge?.niveau === 'plein'" @click="envoyer">
        Envoyer
      </button>
      <button class="primaire pousse" :disabled="etape.etat !== 'en_attente'" @click="emit('rediger')">
        Rédiger {{ etape.produit === 'plan' ? 'le plan' : 'la spec' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.messages { display: flex; flex-direction: column; gap: 0.5rem; }
.bulle { max-width: 80%; padding: 0.5rem 0.9rem; border-radius: 1rem; }
.moi { align-self: flex-end; background: var(--bleu-doux); white-space: pre-wrap; border-bottom-right-radius: 0.25rem; }
.agent { align-self: flex-start; background: var(--creux); border-bottom-left-radius: 0.25rem; }
.systeme, .outil { color: var(--discret); }
.outil { font-size: 0.85em; }
summary { cursor: pointer; }
</style>
