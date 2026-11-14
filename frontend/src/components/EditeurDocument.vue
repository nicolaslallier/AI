<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Etape } from '../api'
import { rendreMarkdown } from '../markdown'

const props = defineProps<{ etape: Etape; message?: string }>()
const emit = defineEmits<{ enregistrer: [contenu: string]; valider: [] }>()
const doc = computed(() => props.etape.document!)
const texte = ref(doc.value.contenu)
watch(() => doc.value.contenu, (c) => (texte.value = c))
const modifie = computed(() => texte.value !== doc.value.contenu)
const validee = computed(() => doc.value.etat === 'validee')
</script>

<template>
  <section>
    <h2>{{ etape.produit === 'plan' ? 'Plan' : 'Spec' }} <span v-if="validee" class="valide">Validée</span></h2>
    <div class="cote">
      <textarea v-if="!validee" v-model="texte" rows="20"></textarea>
      <div class="apercu" v-html="rendreMarkdown(validee ? doc.contenu : texte)"></div>
    </div>
    <p v-if="message" class="erreur">{{ message }}</p>
    <template v-if="!validee">
      <button :disabled="!modifie" @click="emit('enregistrer', texte)">Enregistrer</button>
      <button :disabled="modifie || etape.etat !== 'en_attente' || doc.etat !== 'brouillon'" @click="emit('valider')">
        Valider
      </button>
    </template>
  </section>
</template>

<style scoped>
.cote { display: flex; gap: 1rem; }
.cote > * { flex: 1; min-width: 0; }
.apercu { border: 1px solid #e5e7eb; padding: 0 0.75rem; overflow: auto; }
.valide { background: #bbf7d0; padding: 0.1rem 0.5rem; border-radius: 0.75rem; font-size: 0.6em; }
.erreur { color: #b91c1c; }
</style>
