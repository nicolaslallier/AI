<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  enregistrerDocument, envoyerMessage, ErreurApi, lirePipeline, reessayer, rediger, valider,
  type PipelineDetail,
} from '../api'
import { ecouterFlux } from '../flux'
import EtatBadge from '../components/EtatBadge.vue'
import ChatEtape from '../components/ChatEtape.vue'
import EditeurDocument from '../components/EditeurDocument.vue'

const props = defineProps<{ id: string }>()
const pipeline = ref<PipelineDetail | null>(null)
const partiels = reactive<Record<number, string>>({})
const message = ref('')
const abonnements = new Map<number, () => void>()

function desabonner(etapeId: number) {
  abonnements.get(etapeId)?.()
  abonnements.delete(etapeId)
  delete partiels[etapeId]
}

function abonner(etapeId: number) {
  if (abonnements.has(etapeId)) return
  const fini = () => {
    desabonner(etapeId)
    charger(false)
  }
  abonnements.set(
    etapeId,
    ecouterFlux(etapeId, {
      partiel: (t) => (partiels[etapeId] = t),
      delta: (t) => (partiels[etapeId] = (partiels[etapeId] ?? '') + t),
      fin: fini,
      erreur: fini,
    }),
  )
}

async function charger(ecouter = true) {
  try {
    pipeline.value = await lirePipeline(Number(props.id))
  } catch (e) {
    message.value = (e as Error).message
    return
  }
  if (ecouter) for (const e of pipeline.value.etapes) if (e.etat === 'en_cours') abonner(e.id)
}

async function action(f: () => Promise<unknown>, ecouter = true) {
  message.value = ''
  try {
    await f()
  } catch (e) {
    if (e instanceof ErreurApi && (e.status === 409 || e.status === 422)) message.value = e.detail
    else message.value = (e as Error).message
    return
  }
  await charger(ecouter)
}

onMounted(charger)
onBeforeUnmount(() => [...abonnements.keys()].forEach(desabonner))
</script>

<template>
  <template v-if="pipeline">
    <h1>{{ pipeline.type }} n°{{ pipeline.id }} <EtatBadge :etat="pipeline.etat" /></h1>
    <p>Projet : <RouterLink :to="`/projets/${pipeline.projet.id}`">{{ pipeline.projet.nom }}</RouterLink></p>
    <div v-for="e in pipeline.etapes" :key="e.id">
      <h2>{{ e.agent }} <EtatBadge :etat="e.etat" /></h2>
      <template v-if="e.etat !== 'a_faire'">
        <EditeurDocument
          v-if="e.document"
          :etape="e"
          :message="message"
          @enregistrer="(c) => action(() => enregistrerDocument(e.id, c), false)"
          @valider="action(() => valider(e.id), false)"
        />
        <ChatEtape
          v-if="e.etat !== 'terminee'"
          :etape="e"
          :partiel="partiels[e.id]"
          :message="e.document ? '' : message"
          @envoyer="(c) => action(() => envoyerMessage(e.id, c))"
          @rediger="action(() => rediger(e.id))"
          @reessayer="action(() => reessayer(e.id))"
        />
      </template>
    </div>
  </template>
  <p v-else-if="message" class="erreur">{{ message }}</p>
</template>
