<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { lireArbreCoffre, lireNoteCoffre, type ArbreCoffre } from '../api'
import { separerFrontmatter } from '../coffre'
import { rendreMarkdown } from '../markdown'

const route = useRoute()
const router = useRouter()
// Arbre paresseux : un niveau chargé à l'ouverture de chaque dossier.
const niveaux = ref<Record<string, ArbreCoffre>>({})
const ouverts = ref<Set<string>>(new Set())
const contenu = ref('')
const erreur = ref('')
const note = computed(() => (typeof route.query.note === 'string' ? route.query.note : ''))
const parties = computed(() => separerFrontmatter(contenu.value))

const nom = (chemin: string) => chemin.split('/').at(-1) ?? chemin

async function charger(dossier: string) {
  try {
    niveaux.value[dossier] = await lireArbreCoffre(dossier)
  } catch (e) {
    erreur.value = (e as Error).message
  }
}

async function basculer(dossier: string) {
  if (ouverts.value.has(dossier)) ouverts.value.delete(dossier)
  else {
    ouverts.value.add(dossier)
    if (!niveaux.value[dossier]) await charger(dossier)
  }
}

// Ordre d'affichage à plat : [dossier ou note, profondeur].
const lignes = computed(() => {
  const out: { type: 'dossier' | 'note'; chemin: string; prof: number }[] = []
  const parcourir = (d: string, prof: number) => {
    const n = niveaux.value[d]
    if (!n) return
    for (const sous of n.dossiers) {
      out.push({ type: 'dossier', chemin: sous, prof })
      if (ouverts.value.has(sous)) parcourir(sous, prof + 1)
    }
    for (const x of n.notes) out.push({ type: 'note', chemin: x.chemin, prof })
  }
  parcourir('', 0)
  return out
})

watch(
  note,
  async (chemin) => {
    contenu.value = ''
    if (!chemin) return
    erreur.value = ''
    try {
      contenu.value = (await lireNoteCoffre(chemin)).contenu
    } catch (e) {
      erreur.value = (e as Error).message
    }
  },
  { immediate: true },
)
charger('')
</script>

<template>
  <h1>Coffre</h1>
  <p v-if="erreur" class="erreur">{{ erreur }}</p>
  <div class="coffre">
    <nav class="arbre">
      <div v-for="l in lignes" :key="l.type + l.chemin" :style="{ paddingLeft: l.prof + 'em' }">
        <button v-if="l.type === 'dossier'" type="button" class="lien" @click="basculer(l.chemin)">
          {{ ouverts.has(l.chemin) ? '▾' : '▸' }} {{ nom(l.chemin) }}
        </button>
        <a v-else href="#" :class="{ actif: l.chemin === note }"
          @click.prevent="router.push({ query: { note: l.chemin } })">{{ nom(l.chemin) }}</a>
      </div>
      <p v-if="Object.values(niveaux).some((n) => n.tronque)" class="vide">
        Liste tronquée à 1000 entrées par dossier.
      </p>
    </nav>
    <article v-if="note">
      <h2>{{ note }}</h2>
      <pre v-if="parties.frontmatter">{{ parties.frontmatter }}</pre>
      <div class="markdown" v-html="rendreMarkdown(parties.corps)"></div>
    </article>
    <p v-else class="vide">Choisir une note.</p>
  </div>
</template>

<style scoped>
.coffre {
  display: grid;
  grid-template-columns: minmax(12rem, 20rem) 1fr;
  gap: 1rem;
}
.arbre {
  overflow-x: auto;
}
.lien {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font: inherit;
  color: inherit;
}
.actif {
  font-weight: bold;
}
@media (max-width: 700px) {
  .coffre {
    grid-template-columns: 1fr;
  }
}
</style>
