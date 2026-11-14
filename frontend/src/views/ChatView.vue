<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  confirmerAction, creerConversation, envoyerMessageConversation, lireConversation, listerConversations, refuserAction, reessayerConversation,
  supprimerConversation, type ConversationDetail, type ConversationResume,
} from '../api'
import { fil, trier } from '../conversations'
import { ecouterFlux } from '../flux'
import { rendreMarkdown } from '../markdown'
import CarteAction from '../components/CarteAction.vue'
import JaugeContexte from '../components/JaugeContexte.vue'

const props = defineProps<{ id?: string }>()
const router = useRouter()
const liste = ref<ConversationResume[]>([])
const conv = ref<ConversationDetail | null>(null)
const partiel = ref('')
const outils = ref<string[]>([])
const message = ref('')
const saisie = ref('')
let arret: (() => void) | null = null
let demonte = false

function desabonner() {
  arret?.()
  arret = null
  partiel.value = ''
  outils.value = []
}

async function rafraichirListe() {
  try {
    const l = await listerConversations()
    if (!demonte) liste.value = trier(l)
  } catch (e) {
    if (!demonte) message.value = (e as Error).message
  }
}

async function charger(ecouter = true) {
  desabonner()
  if (!props.id) {
    conv.value = null
    return
  }
  const id = Number(props.id)
  try {
    const c = await lireConversation(id)
    if (demonte || String(id) !== props.id) return
    conv.value = c
  } catch (e) {
    if (!demonte) message.value = (e as Error).message
    return
  }
  if (ecouter && conv.value.etat === 'en_cours') abonner(id)
}

function abonner(id: number) {
  if (arret) return
  const fini = () => {
    desabonner()
    if (demonte || String(id) !== props.id) return
    charger(false)
    rafraichirListe()
  }
  arret = ecouterFlux(`/api/conversations/${id}/flux`, {
    partiel: (t) => (partiel.value = t),
    delta: (t) => (partiel.value += t),
    outil: (l) => (outils.value = [...outils.value, l]),
    fin: fini,
    erreur: fini,
  })
}

async function action(f: () => Promise<unknown>): Promise<boolean> {
  message.value = ''
  try {
    await f()
  } catch (e) {
    if (!demonte) message.value = (e as Error).message
    return false
  }
  return !demonte
}

async function nouvelle() {
  message.value = ''
  try {
    const c = await creerConversation()
    await rafraichirListe()
    router.push({ name: 'conversation', params: { id: c.id } })
  } catch (e) {
    message.value = (e as Error).message
  }
}

const bloque = () => conv.value?.etat !== 'pret' || conv.value.jauge?.niveau === 'plein'

async function envoyer() {
  const t = saisie.value.trim()
  if (!t || !conv.value || bloque()) return
  if (await action(() => envoyerMessageConversation(conv.value!.id, t))) {
    saisie.value = ''
    await charger()
    rafraichirListe()
  }
}

function surEntree(e: KeyboardEvent) {
  if (e.isComposing) return
  e.preventDefault()
  envoyer()
}

async function reessayer() {
  if (conv.value && (await action(() => reessayerConversation(conv.value!.id)))) await charger()
}

async function supprimer() {
  if (!conv.value || !confirm('Supprimer cette conversation ? Cette action est définitive.')) return
  if (await action(() => supprimerConversation(conv.value!.id))) {
    await rafraichirListe()
    router.push({ name: 'chat' })
  }
}

const envoi = ref(false)
async function trancher(f: (id: number) => Promise<unknown>, id: number) {
  envoi.value = true
  try {
    if (await action(() => f(id))) await charger()
  } finally {
    envoi.value = false
  }
}

watch(
  () => props.id,
  () => {
    message.value = ''
    conv.value = null
    charger()
  },
  { immediate: true },
)
rafraichirListe()
onBeforeUnmount(() => {
  demonte = true
  desabonner()
})
</script>

<template>
  <div class="chat">
    <aside class="pile">
      <button class="primaire" @click="nouvelle">+ Nouvelle</button>
      <RouterLink
        v-for="c in liste"
        :key="c.id"
        :to="{ name: 'conversation', params: { id: c.id } }"
        :class="['carte', { actif: String(c.id) === id }]"
      >
        {{ c.titre || `Conversation n°${c.id}` }}
      </RouterLink>
    </aside>
    <section class="pile">
      <p v-if="message" class="erreur">{{ message }}</p>
      <p v-if="!id" class="discret">Choisis une conversation ou crée-en une nouvelle.</p>
      <template v-else-if="conv">
        <div class="rangee">
          <h1>{{ conv.titre || `Conversation n°${conv.id}` }}</h1>
          <button class="danger pousse" :disabled="conv.etat === 'en_cours'" @click="supprimer">Supprimer</button>
        </div>
        <JaugeContexte v-if="conv.jauge" :jauge="conv.jauge" />
        <div class="messages">
          <template v-for="e in fil(conv.messages, conv.actions)" :key="`${e.type}${(e.type === 'message' ? e.message : e.action).id}`">
          <CarteAction
            v-if="e.type === 'action'"
            :action="e.action"
            :occupe="conv.etat === 'en_cours' || envoi"
            @confirmer="trancher(confirmerAction, e.action.id)"
            @refuser="trancher(refuserAction, e.action.id)"
          />
          <div
            v-else
            :class="['bulle', e.message.role === 'user' ? 'moi' : 'agent', { systeme: e.message.role === 'system' }]"
          >
            <details v-if="e.message.role === 'tool'"><summary>🔎 {{ e.message.outil }}</summary><pre>{{ e.message.contenu }}</pre></details>
            <em v-else-if="e.message.role === 'system'">{{ e.message.contenu }}</em>
            <template v-else-if="e.message.role === 'user'">{{ e.message.contenu }}</template>
            <div v-else class="markdown" v-html="rendreMarkdown(e.message.contenu)"></div>
          </div>
          </template>
          <div v-if="conv.etat === 'en_cours'" class="bulle agent">
            <div v-if="partiel" class="markdown" v-html="rendreMarkdown(partiel)"></div>
            <em v-else class="discret">L'agent réfléchit…</em>
            <div v-for="(o, i) in outils" :key="i" class="outil">🔎 {{ o }}</div>
          </div>
        </div>
        <p v-if="conv.etat === 'erreur'" class="erreur">
          {{ conv.erreur }} <button type="button" @click="reessayer">Réessayer</button>
        </p>
        <textarea
          v-model="saisie"
          rows="3"
          placeholder="Écris ton message… (Entrée pour envoyer, Maj+Entrée pour une nouvelle ligne)"
          :disabled="bloque()"
          @keydown.enter.exact="surEntree"
        ></textarea>
        <div class="rangee">
          <button :disabled="!saisie.trim() || bloque()" @click="envoyer">Envoyer</button>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.chat { display: grid; grid-template-columns: 16rem 1fr; gap: 1rem; align-items: start; }
.carte.actif { border-color: var(--bleu-doux); font-weight: 600; }
.messages { display: flex; flex-direction: column; gap: 0.5rem; }
.bulle { max-width: 80%; padding: 0.5rem 0.9rem; border-radius: 1rem; }
.moi { align-self: flex-end; background: var(--bleu-doux); white-space: pre-wrap; border-bottom-right-radius: 0.25rem; }
.agent { align-self: flex-start; background: var(--creux); border-bottom-left-radius: 0.25rem; }
.systeme, .outil { color: var(--discret); }
.outil { font-size: 0.85em; }
summary { cursor: pointer; }
</style>
