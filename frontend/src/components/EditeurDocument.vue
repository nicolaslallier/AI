<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Etape } from '../api'
import { rendreMarkdown, sansBlocModele } from '../markdown'

const props = defineProps<{ etape: Etape; message?: string; sansApercu?: boolean }>()
const emit = defineEmits<{ enregistrer: [contenu: string]; valider: [] }>()
const doc = computed(() => props.etape.document!)
const texte = ref(doc.value.contenu)
watch(() => doc.value.contenu, (c) => (texte.value = c))
const modifie = computed(() => texte.value !== doc.value.contenu)
const validee = computed(() => doc.value.etat === 'validee')
// Le bloc du modèle ArchiMate n'existe que dans les documents de la vision et des volets.
const masquerModele = computed(() => props.etape.produit === 'vision' || props.etape.produit === 'volet')
const afficher = (md: string) => rendreMarkdown(masquerModele.value ? sansBlocModele(md) : md)
const automatique = computed(() => props.etape.produit === 'volet') // validé sans action de l'utilisateur
const titres: Record<string, string> = { plan: 'Plan', vision: 'Vision', volet: 'Volet', architecture: 'Synthèse de l’architecture' }
</script>

<template>
  <section class="pile">
    <h3>{{ titres[etape.produit ?? ''] ?? 'Spec' }} <span v-if="validee" class="badge terminee">Validée</span></h3>
    <div class="cote">
      <textarea v-if="!validee" v-model="texte" rows="20"></textarea>
      <div v-if="!sansApercu" class="apercu markdown" v-html="afficher(validee ? doc.contenu : texte)"></div>
    </div>
    <p v-if="message" class="erreur">{{ message }}</p>
    <template v-if="!validee">
      <div class="rangee">
        <button :disabled="!modifie" @click="emit('enregistrer', texte)">Enregistrer</button>
        <button
          v-if="!automatique"
          class="primaire"
          :disabled="modifie || etape.etat !== 'en_attente' || doc.etat !== 'brouillon'"
          @click="emit('valider')"
        >
          Valider
        </button>
        <small v-if="modifie">Enregistre tes modifications avant de valider.</small>
      </div>
    </template>
  </section>
</template>

<style scoped>
.cote { display: flex; gap: 1rem; flex-wrap: wrap; }
.cote > * { flex: 1 1 20rem; min-width: 0; }
.cote textarea { font-family: ui-monospace, monospace; font-size: 0.9rem; }
.apercu { border: 1px solid var(--bord); border-radius: 0.55rem; padding: 0.75rem 1rem; overflow: auto; max-height: 32rem; }
</style>
