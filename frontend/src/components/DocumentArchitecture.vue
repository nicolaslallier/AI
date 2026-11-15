<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ErreurApi, lireArchitecture, urlDocumentArchitecture, urlModeleArchimate, type Etape } from '../api'
import { rendreMarkdown } from '../markdown'
import EditeurDocument from './EditeurDocument.vue'

const props = defineProps<{ pipelineId: number; etape: Etape; etapes: Etape[]; message?: string }>()
defineEmits<{ enregistrer: [contenu: string]; valider: [] }>()
const assemble = ref<string | null>(null)
const erreur = ref('')

// Le document assemblé change quand la synthèse change ou quand un volet se termine.
const cle = computed(
  () =>
    `${props.etape.document?.version}/${props.etape.document?.etat}/` +
    props.etapes.filter((e) => e.etat === 'terminee').length,
)
let dernier = 0
watch(
  cle,
  async () => {
    const appel = ++dernier
    try {
      const md = await lireArchitecture(props.pipelineId)
      if (appel === dernier) {
        assemble.value = md
        erreur.value = ''
      }
    } catch (e) {
      if (appel !== dernier) return
      assemble.value = null
      // 409 : pas encore rédigée, on n'affiche rien
      erreur.value = e instanceof ErreurApi && e.status === 409 ? '' : (e as Error).message
    }
  },
  { immediate: true },
)
</script>

<template>
  <section class="pile">
    <template v-if="assemble !== null">
      <div class="rangee">
        <a :href="urlModeleArchimate(pipelineId)" download class="bouton">Télécharger le modèle ArchiMate</a>
        <a :href="urlDocumentArchitecture(pipelineId)" download class="bouton">Télécharger le document</a>
      </div>
      <div class="carte markdown" v-html="rendreMarkdown(assemble)"></div>
    </template>
    <p v-if="erreur" class="erreur">{{ erreur }}</p>
    <EditeurDocument
      :etape="etape"
      :message="message"
      sans-apercu
      @enregistrer="(c) => $emit('enregistrer', c)"
      @valider="$emit('valider')"
    />
  </section>
</template>
