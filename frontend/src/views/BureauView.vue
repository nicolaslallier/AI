<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { lireBureau, lirePoste, type Bureau, type EtatPoste, type PosteDetail } from '../api'
import { ecouterEvenements, regrouper } from '../evenements'
import JaugeContexte from '../components/JaugeContexte.vue'

const libelles: Record<EtatPoste, string> = {
  libre: 'libre',
  au_travail: 'au travail',
  en_attente: 'en attente de Nicolas',
  en_erreur: 'en erreur',
}
const bureau = ref<Bureau | null>(null)
const ouvert = ref<string | null>(null)
const detail = ref<PosteDetail | null>(null)
const erreur = ref('')
let minuteur: ReturnType<typeof setInterval> | undefined
let arreter: (() => void) | undefined
let fini = false

async function charger() {
  if (fini) return
  try {
    bureau.value = await lireBureau()
    erreur.value = ''
    if (ouvert.value && !bureau.value.postes[ouvert.value]) {
      ouvert.value = null
      detail.value = null
    }
    if (ouvert.value) await chargerDetail(ouvert.value)
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

async function chargerDetail(nom: string) {
  const d = await lirePoste(nom)
  if (ouvert.value !== nom) return // un autre clic a pu passer entre-temps
  const premier = !detail.value
  detail.value = d
  if (premier) {
    await nextTick()
    document.getElementById('detail-poste')?.scrollIntoView?.({ block: 'nearest' })
  }
}

async function basculer(nom: string) {
  if (ouvert.value === nom) {
    ouvert.value = null
    detail.value = null
    return
  }
  ouvert.value = nom
  detail.value = null
  try {
    await chargerDetail(nom)
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

const duree = (ms: number) => (ms < 1000 ? `${ms} ms` : `${Math.round(ms / 1000)} s`)
const debut = (iso: string) => new Date(iso).toLocaleString('fr-FR')

onMounted(() => {
  charger()
  minuteur = setInterval(charger, 60000) // filet de sécurité ; les événements font le reste
  // un signal part à chaque appel au modèle : on regroupe
  const recharger = regrouper(charger, 1000)
  arreter = ecouterEvenements({ pipelines: recharger, bureau: recharger })
})
onUnmounted(() => {
  fini = true
  clearInterval(minuteur)
  arreter?.()
})
</script>

<template>
  <h1>Bureau</h1>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <template v-if="bureau">
    <section v-for="(g, gi) in bureau.groupes" :key="gi" class="groupe">
      <h2>{{ g.nom ?? 'Hors pipeline' }}</h2>
      <div class="postes">
        <template v-for="(nom, i) in g.agents" :key="i">
          <span v-if="g.nom !== null && i > 0" class="fleche" aria-hidden="true">→</span>
          <div v-if="bureau.postes[nom]" class="carte poste" :class="bureau.postes[nom].etat">
            <button class="nom" :aria-expanded="ouvert === nom" aria-controls="detail-poste" @click="basculer(nom)">
              {{ nom }}
            </button>
            <span class="pastille" :class="bureau.postes[nom].etat">
              {{ libelles[bureau.postes[nom].etat] }}
            </span>
            <ul v-if="bureau.postes[nom].travaux.length" class="travaux">
              <li v-for="t in bureau.postes[nom].travaux" :key="t.sorte + t.lien + t.libelle">
                <RouterLink :to="t.lien">{{ t.libelle }}</RouterLink>
                <small v-if="t.tour !== null"> · tour {{ t.tour }}</small>
                <small> · {{ libelles[t.etat] }}</small>
                <JaugeContexte v-if="t.jauge" :jauge="t.jauge" compacte />
              </li>
            </ul>
            <small class="discret">
              {{ bureau.postes[nom].appels_jour }} appels ·
              {{ bureau.postes[nom].jetons_jour.toLocaleString('fr-FR') }} jetons
            </small>
          </div>
        </template>
      </div>
    </section>
    <section v-if="ouvert && detail" id="detail-poste" class="carte detail">
      <h2>{{ detail.nom }}</h2>
      <p>{{ detail.description }}</p>
      <p>
        Modèle : {{ detail.modele }}
        <template v-if="detail.modele_si_meme"> (si même : {{ detail.modele_si_meme }})</template>
      </p>
      <p>Outils permis : {{ detail.outils.length ? detail.outils.join(', ') : 'aucun' }}</p>
      <p v-if="!detail.missions.length" class="discret">Aucune mission.</p>
      <table v-else>
        <thead>
          <tr>
            <th>Début</th><th>Durée</th><th>Appels</th><th>Jetons</th><th>Issue</th><th>Travail</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in detail.missions" :key="m.mission">
            <td>{{ debut(m.debut) }}</td>
            <td>{{ duree(m.duree_ms) }}</td>
            <td>{{ m.appels }}</td>
            <td>{{ (m.jetons_entree + m.jetons_sortie).toLocaleString('fr-FR') }}</td>
            <td>{{ m.issue }}</td>
            <td>
              <RouterLink v-if="m.lien" :to="m.lien">{{ m.libelle }}</RouterLink>
              <template v-else>{{ m.libelle ?? '' }}</template>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </template>
</template>

<style scoped>
.postes { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
.poste { display: flex; flex-direction: column; gap: 0.35rem; min-width: 11rem; max-width: 100%; }
.poste.au_travail { border-color: var(--succes); }
.poste.en_attente { border-color: var(--alerte); }
.poste.en_erreur { border-color: var(--danger); }
.nom { font-weight: 700; text-align: left; }
.pastille { align-self: flex-start; padding: 0.1rem 0.6rem; border-radius: 999px; font-size: 0.85rem; background: var(--gris-doux); }
.pastille.au_travail { color: var(--succes); }
.pastille.en_attente { color: var(--alerte); }
.pastille.en_erreur { color: var(--danger); }
.travaux { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 0.3rem; }
.fleche { color: var(--discret); font-size: 1.4rem; }
.detail { margin-top: 1rem; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 0.25rem 0.6rem; border-bottom: 1px solid var(--bord); }
</style>
