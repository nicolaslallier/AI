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

async function envoyer() {
  const texte = saisie.value.trim()
  if (!texte || reflechit.value) return
  fil.value.push({ role: 'moi', texte })
  saisie.value = ''
  erreur.value = ''
  reflechit.value = true
  try {
    fil.value.push({ role: 'agent', texte: await demanderMusique(texte) })
  } catch (e) {
    erreur.value = (e as Error).message
    saisie.value = texte
  } finally {
    reflechit.value = false
  }
}
</script>

<template>
  <h1>Musique</h1>
  <p class="vide">L'agent n'a pas de mémoire : chaque message est traité seul.</p>
  <div v-for="(l, i) in fil" :key="i" :class="['message', l.role]">
    <p v-if="l.role === 'moi'">{{ l.texte }}</p>
    <div v-else class="markdown" v-html="rendreMarkdown(l.texte)"></div>
  </div>
  <p v-if="reflechit" class="vide">L'agent réfléchit…</p>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <form @submit.prevent="envoyer">
    <textarea v-model="saisie" rows="3" maxlength="4000" placeholder="Une question sur la collection de disques…"
      @keydown.enter.exact.prevent="envoyer"></textarea>
    <button type="submit" :disabled="reflechit || !saisie.trim()">Envoyer</button>
  </form>
</template>
