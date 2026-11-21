<script setup lang="ts">
import { ref } from 'vue'
import { demanderMusique } from '../api'
import { rendreMarkdown } from '../markdown'

interface Ligne {
  role: 'moi' | 'agent'
  texte: string
}

const fil = ref<Ligne[]>([])
const saisie = ref('')
const erreur = ref('')
const reflechit = ref(false)
let contextId: string | null = null

async function envoyer() {
  const texte = saisie.value.trim()
  if (!texte || reflechit.value) return
  fil.value.push({ role: 'moi', texte })
  saisie.value = ''
  erreur.value = ''
  reflechit.value = true
  try {
    const r = await demanderMusique(texte, contextId)
    contextId = r.context_id
    fil.value.push({ role: 'agent', texte: r.texte })
  } catch (e) {
    erreur.value = (e as Error).message
  } finally {
    reflechit.value = false
  }
}

function nouvelle() {
  fil.value = []
  contextId = null
  erreur.value = ''
}
</script>

<template>
  <h1>Musique</h1>
  <button type="button" @click="nouvelle" :disabled="reflechit">Nouvelle conversation</button>
  <div v-for="(l, i) in fil" :key="i" :class="['message', l.role]">
    <p v-if="l.role === 'moi'">{{ l.texte }}</p>
    <div v-else class="markdown" v-html="rendreMarkdown(l.texte)"></div>
  </div>
  <p v-if="reflechit" class="vide">L'agent réfléchit…</p>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <form @submit.prevent="envoyer">
    <textarea v-model="saisie" rows="3" placeholder="Une question sur la collection de disques…"
      @keydown.enter.exact.prevent="envoyer"></textarea>
    <button type="submit" :disabled="reflechit || !saisie.trim()">Envoyer</button>
  </form>
</template>
