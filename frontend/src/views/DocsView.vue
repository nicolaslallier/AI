<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  creerCarteDoc, listerCartesDoc, listerProjets, modifierCarteDoc, relancerCarteDoc, renvoyerCarteDoc,
  supprimerCarteDoc, validerCarteDoc, type CarteDoc, type Projet,
} from '../api'
import { COLONNES_DOC, EN_COURS, GENRES, grouper, resynchroniser } from '../docs'
import { ecouterEvenements, regrouper } from '../evenements'
import { rendreMarkdown } from '../markdown'

const cartes = ref<CarteDoc[]>([])
const projets = ref<Projet[]>([])
const erreur = ref('')
const nouvelle = ref<{ projet_id: number | null; genre: string; titre: string; consigne: string } | null>(null)
const ouverteId = ref<number | null>(null)
const brouillon = ref('')
let base = '' // contenu du serveur sur lequel le brouillon s'appuie
const remarques = ref('')
const forcer = ref(false)
let minuteur: ReturnType<typeof setInterval> | undefined
let arreter: (() => void) | undefined

const colonnes = computed(() => grouper(cartes.value))
const ouverte = computed(() => cartes.value.find((c) => c.id === ouverteId.value) ?? null)
const enCours = computed(() => !!ouverte.value && EN_COURS.includes(ouverte.value.colonne))
watch(
  () => ouverte.value?.contenu,
  (nouveau) => {
    if (nouveau !== undefined) ({ brouillon: brouillon.value, base } = resynchroniser(brouillon.value, base, nouveau))
  },
)

async function charger() {
  try {
    cartes.value = await listerCartesDoc()
  } catch (e) {
    erreur.value = (e as Error).message
  }
}
async function agir(f: () => Promise<unknown>, fermer = false) {
  erreur.value = ''
  try {
    await f()
    if (fermer) ouverteId.value = null
  } catch (e) {
    erreur.value = (e as Error).message
  }
  await charger()
}
function ouvrir(c: CarteDoc) {
  ouverteId.value = c.id
  brouillon.value = base = c.contenu
  remarques.value = ''
  forcer.value = false
  erreur.value = ''
}
async function creer() {
  const n = nouvelle.value!
  if (n.projet_id === null) return
  await agir(async () => {
    await creerCarteDoc({ ...n, projet_id: n.projet_id! })
    nouvelle.value = null
  })
}
const lignes = (t: string) => t.split('\n').map((l) => l.trim()).filter(Boolean)

onMounted(async () => {
  charger()
  try {
    projets.value = await listerProjets()
  } catch (e) {
    erreur.value = (e as Error).message
  }
  minuteur = setInterval(charger, 60000) // filet de sécurité ; les événements font le reste
  arreter = ecouterEvenements({ docs: regrouper(charger) })
})
onBeforeUnmount(() => {
  clearInterval(minuteur)
  arreter?.()
})
</script>

<template>
  <div class="titre">
    <h1>Docs</h1>
    <button class="primaire pousse" @click="nouvelle = { projet_id: null, genre: 'guide', titre: '', consigne: '' }">
      + Nouvelle doc
    </button>
  </div>
  <p v-if="erreur && !ouverte" class="erreur">{{ erreur }}</p>
  <div class="colonnes">
    <section v-for="col in COLONNES_DOC" :key="col.valeur" class="colonne">
      <h3>{{ col.libelle }} <span class="badge">{{ colonnes[col.valeur].length }}</span></h3>
      <button v-for="c in colonnes[col.valeur]" :key="c.id" class="carte" @click="ouvrir(c)">
        <strong>{{ c.titre }}</strong>
        <small>{{ c.projet_nom }} · {{ c.genre }}<template v-if="c.renvois"> · {{ c.renvois }} renvoi(s)</template></small>
        <small v-if="c.erreur" class="erreur">{{ c.erreur }}</small>
      </button>
    </section>
  </div>

  <div v-if="nouvelle" class="fond" @click.self="nouvelle = null">
    <form class="modale" @submit.prevent="creer">
      <h2>Nouvelle doc</h2>
      <label>Projet
        <select v-model="nouvelle.projet_id" required>
          <option v-for="p in projets" :key="p.id" :value="p.id">{{ p.nom }}</option>
        </select>
      </label>
      <label>Genre
        <select v-model="nouvelle.genre"><option v-for="g in GENRES" :key="g">{{ g }}</option></select>
      </label>
      <label>Titre <input v-model="nouvelle.titre" required maxlength="200" /></label>
      <label>Consigne <textarea v-model="nouvelle.consigne" rows="4" /></label>
      <p v-if="erreur" class="erreur">{{ erreur }}</p>
      <div class="actions">
        <button type="button" @click="nouvelle = null">Annuler</button>
        <button class="primaire" type="submit">Créer</button>
      </div>
    </form>
  </div>

  <div v-if="ouverte" class="fond" @click.self="ouverteId = null">
    <div class="modale large">
      <h2>{{ ouverte.titre }}</h2>
      <p>
        <small>{{ ouverte.projet_nom }} · {{ ouverte.genre }} · <code>{{ ouverte.chemin }}</code></small>
        <br />
        <RouterLink v-if="ouverte.pipeline_id" :to="`/pipelines/${ouverte.pipeline_id}`">Pipeline</RouterLink>
        <template v-if="ouverte.colonne === 'publie'">
          · <RouterLink :to="{ path: '/coffre', query: { note: ouverte.chemin } }">Voir dans le coffre</RouterLink>
        </template>
      </p>
      <p v-if="ouverte.consigne"><em>{{ ouverte.consigne }}</em></p>
      <p v-if="ouverte.erreur" class="erreur">Erreur : {{ ouverte.erreur }}</p>
      <div v-if="ouverte.remarques.length">
        <h3>Remarques</h3>
        <ul><li v-for="(r, i) in ouverte.remarques" :key="i">{{ r }}</li></ul>
      </div>
      <template v-if="ouverte.colonne === 'a_valider'">
        <textarea v-model="brouillon" rows="14" aria-label="Contenu du document" />
        <button :disabled="brouillon === ouverte.contenu" @click="agir(() => modifierCarteDoc(ouverte!.id, { contenu: brouillon }))">
          Enregistrer le texte
        </button>
      </template>
      <div v-if="ouverte.contenu" class="apercu" v-html="rendreMarkdown(ouverte.contenu)" />
      <p v-if="erreur" class="erreur">{{ erreur }}</p>
      <div v-if="!enCours" class="actions">
        <template v-if="ouverte.colonne === 'a_valider'">
          <label><input v-model="forcer" type="checkbox" /> Écraser la note du coffre</label>
          <button
            class="primaire"
            :disabled="brouillon !== ouverte.contenu"
            :title="brouillon !== ouverte.contenu ? 'Enregistrer le texte avant de valider' : ''"
            @click="agir(() => validerCarteDoc(ouverte!.id, forcer))"
          >
            Valider
          </button>
        </template>
        <textarea v-model="remarques" rows="2" placeholder="Remarques, une par ligne" aria-label="Remarques de renvoi" />
        <button :disabled="!lignes(remarques).length" @click="agir(() => renvoyerCarteDoc(ouverte!.id, lignes(remarques)))">
          Renvoyer
        </button>
        <button @click="agir(() => relancerCarteDoc(ouverte!.id))">Relancer</button>
        <button class="danger" @click="agir(() => supprimerCarteDoc(ouverte!.id), true)">Supprimer</button>
      </div>
      <p v-else><small>En cours : rien à faire pour l'instant.</small></p>
      <div class="actions"><button @click="ouverteId = null">Fermer</button></div>
    </div>
  </div>
</template>

<style scoped>
.colonnes { display: grid; grid-template-columns: repeat(5, minmax(13rem, 1fr)); gap: 0.75rem; overflow-x: auto; align-items: start; }
.colonne { background: var(--creux); border-radius: var(--rayon); padding: 0.6rem; min-height: 8rem; display: flex; flex-direction: column; gap: 0.5rem; }
.colonne h3 { display: flex; justify-content: space-between; align-items: center; padding: 0.1rem 0.25rem; }
.carte { display: flex; flex-direction: column; gap: 0.2rem; text-align: left; background: var(--surface); border-radius: var(--rayon); padding: 0.5rem; }
.fond { position: fixed; inset: 0; background: #0008; display: flex; align-items: center; justify-content: center; z-index: 10; }
.modale { background: var(--surface); padding: 1.25rem; border-radius: var(--rayon); width: min(40rem, 95vw); max-height: 90vh; overflow: auto; display: flex; flex-direction: column; gap: 0.75rem; box-sizing: border-box; }
.modale.large { width: min(60rem, 95vw); }
.modale label { display: flex; flex-direction: column; gap: 0.25rem; }
.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: flex-end; align-items: center; }
.apercu { border-top: 1px solid var(--creux); padding-top: 0.5rem; }
</style>
