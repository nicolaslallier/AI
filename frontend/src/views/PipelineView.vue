<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  annulerPipeline, enregistrerDocument, lireKanban, envoyerMessage, ErreurApi, lirePipeline, reessayer, rediger, valider,
  type PipelineDetail, type Proposition,
} from '../api'
import { ecouterFlux } from '../flux'
import EtatBadge from '../components/EtatBadge.vue'
import ChatEtape from '../components/ChatEtape.vue'
import EditeurDocument from '../components/EditeurDocument.vue'

const props = defineProps<{ id: string }>()
const pipeline = ref<PipelineDetail | null>(null)
const partiels = reactive<Record<number, string>>({})
const message = ref('')
const outils = reactive<Record<number, string[]>>({})
const propositions = ref<Proposition[]>([])
const abonnements = new Map<number, () => void>()
let demonte = false

function desabonner(etapeId: number) {
  abonnements.get(etapeId)?.()
  abonnements.delete(etapeId)
  delete partiels[etapeId]
  delete outils[etapeId]
}

function abonner(etapeId: number) {
  if (demonte || abonnements.has(etapeId)) return
  const fini = () => {
    desabonner(etapeId)
    charger(false)
  }
  abonnements.set(
    etapeId,
    ecouterFlux(etapeId, {
      partiel: (t) => (partiels[etapeId] = t),
      delta: (t) => (partiels[etapeId] = (partiels[etapeId] ?? '') + t),
      outil: (l) => (outils[etapeId] = [...(outils[etapeId] ?? []), l]),
      fin: fini,
      erreur: fini,
    }),
  )
}

async function charger(ecouter = true) {
  try {
    const p = await lirePipeline(Number(props.id))
    if (demonte) return
    pipeline.value = p
  } catch (e) {
    if (demonte) return
    message.value = (e as Error).message
    return
  }
  if (pipeline.value.etapes.some((e) => e.produit === 'taches')) {
    try {
      const k = await lireKanban(pipeline.value.projet.id)
      if (!demonte) propositions.value = k.propositions
    } catch {
      /* comptage indisponible : on n'empêche ni l'affichage ni l'abonnement */
    }
  }
  if (demonte) return
  if (ecouter) for (const e of pipeline.value.etapes) if (e.etat === 'en_cours') abonner(e.id)
}

async function action(f: () => Promise<unknown>, ecouter = true): Promise<boolean> {
  message.value = ''
  try {
    await f()
  } catch (e) {
    if (demonte) return false
    if (e instanceof ErreurApi && (e.status === 409 || e.status === 422)) message.value = e.detail
    else message.value = (e as Error).message
    return false
  }
  if (demonte) return true
  await charger(ecouter)
  return true
}

async function annuler() {
  if (!confirm('Annuler ce pipeline ? Cette action est définitive.')) return
  await action(() => annulerPipeline(Number(props.id)), false)
}

onMounted(charger)
onBeforeUnmount(() => {
  demonte = true
  ;[...abonnements.keys()].forEach(desabonner)
})
</script>

<template>
  <template v-if="pipeline">
    <h1>{{ pipeline.type }} n°{{ pipeline.id }} <EtatBadge :etat="pipeline.etat" /></h1>
    <button v-if="pipeline.etat !== 'terminee' && pipeline.etat !== 'echouee'" @click="annuler">
      Annuler le pipeline
    </button>
    <p>Projet : <RouterLink :to="`/projets/${pipeline.projet.id}`">{{ pipeline.projet.nom }}</RouterLink></p>
    <div v-for="e in pipeline.etapes" :key="e.id">
      <h2>
        {{ e.agent }} <EtatBadge :etat="e.etat" />
        <small v-if="e.sha">SHA {{ e.sha.slice(0, 7) }}</small>
      </h2>
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
          :outils="outils[e.id]"
          :propositions="e.produit === 'taches' ? propositions.filter((x) => x.etape_id === e.id && x.etat === 'ouverte').length : undefined"
          :projet-id="pipeline.projet.id"
          :message="e.document ? '' : message"
          @envoyer="(c, vider) => action(() => envoyerMessage(e.id, c)).then((ok) => ok && vider())"
          @rediger="action(() => rediger(e.id))"
          @reessayer="action(() => reessayer(e.id))"
        />
      </template>
    </div>
  </template>
  <p v-else-if="message" class="erreur">{{ message }}</p>
</template>
