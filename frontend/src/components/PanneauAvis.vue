<script setup lang="ts">
import { computed, ref } from 'vue'
import { changerEtatAvis, demanderAvis, type Document } from '../api'
import { trierAvis } from '../avis'
import { rendreMarkdown } from '../markdown'

const props = defineProps<{ document: Document }>()
const emit = defineEmits<{ change: [] }>()
const avis = computed(() => trierAvis(props.document.avis))
const enCours = computed(() => props.document.avis.filter((a) => a.etat === 'en_cours'))
const brouillon = computed(() => props.document.etat === 'brouillon')
const message = ref('')
const occupe = ref(false)

async function agir(f: () => Promise<unknown>) {
  message.value = ''
  occupe.value = true
  try {
    await f()
    emit('change')
  } catch (e) {
    message.value = (e as Error).message
  } finally {
    occupe.value = false
  }
}
</script>

<template>
  <section v-if="avis.length || brouillon" class="pile">
    <div class="rangee">
      <h3>Avis</h3>
      <button v-if="brouillon" :disabled="occupe || enCours.length > 0" @click="agir(() => demanderAvis(document.id))">
        Demander un avis
      </button>
    </div>
    <p v-if="enCours.length" class="discret">Avis en cours : {{ enCours.map((a) => a.agent).join(', ') }}…</p>
    <p v-if="message" class="erreur">{{ message }}</p>
    <article v-for="a in avis.filter((x) => x.etat !== 'en_cours')" :key="a.id" class="carte pile">
      <div class="rangee">
        <strong>{{ a.agent }}</strong>
        <span v-if="a.ancienne" class="badge">sur une version antérieure</span>
        <span v-if="a.etat !== 'ouvert'" class="badge">{{ a.etat === 'ecarte' ? 'écarté' : 'pris en compte' }}</span>
      </div>
      <div class="markdown" v-html="rendreMarkdown(a.contenu)"></div>
      <div class="rangee">
        <template v-if="a.etat === 'ouvert'">
          <button :disabled="occupe" @click="agir(() => changerEtatAvis(a.id, 'pris_en_compte'))">Pris en compte</button>
          <button :disabled="occupe" @click="agir(() => changerEtatAvis(a.id, 'ecarte'))">Écarté</button>
        </template>
        <button v-else :disabled="occupe" @click="agir(() => changerEtatAvis(a.id, 'ouvert'))">Rouvrir</button>
      </div>
    </article>
  </section>
</template>
