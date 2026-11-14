<script setup lang="ts">
import type { Proposition, Tache } from '../api'

const props = defineProps<{ propositions: Proposition[]; taches: Tache[]; perimees: number | null }>()
const emit = defineEmits<{
  accepter: [Proposition]
  modifier: [Proposition]
  rejeter: [Proposition]
  toutAccepter: [number]
}>()

const CHAMPS = ['titre', 'description', 'criteres', 'fichiers', 'depend_de'] as const
const texte = (v: unknown) => (Array.isArray(v) ? v.join('\n') : String(v ?? ''))
const cible = (p: Proposition) => props.taches.find((t) => t.id === p.tache_id)
// une modification est partielle : seuls les champs présents changent
const avant = (p: Proposition, c: (typeof CHAMPS)[number]) => {
  const t = cible(p)
  return c === 'depend_de' ? t?.depend_de.map((i) => `T${i}`) : t?.[c]
}
const etapes = () => [...new Set(props.propositions.map((p) => p.etape_id))]
</script>

<template>
  <section class="panneau">
    <div class="titre">
      <h2>Propositions de l'agent <span class="badge en_attente">{{ propositions.length }}</span></h2>
      <button v-for="e in etapes()" :key="e" class="pousse" @click="emit('toutAccepter', e)">
        Tout accepter (étape {{ e }})
      </button>
    </div>
    <p v-if="perimees" class="erreur">{{ perimees }} proposition(s) périmée(s) ignorée(s).</p>
    <article v-for="p in propositions" :key="p.id" class="prop">
      <template v-if="p.sorte === 'nouvelle'">
        <strong>Nouvelle : {{ p.donnees.titre }}</strong>
        <p>{{ p.donnees.description }}</p>
        <ul><li v-for="c in (p.donnees.criteres as string[] | undefined) ?? []" :key="c">{{ c }}</li></ul>
        <div v-if="((p.donnees.depend_de as string[] | undefined) ?? []).length">
          Dépend de : {{ (p.donnees.depend_de as string[]).join(', ') }}
        </div>
      </template>
      <template v-else-if="p.sorte === 'modification'">
        <strong>Modification de #{{ p.tache_id }}</strong>
        <template v-for="c in CHAMPS" :key="c">
          <div v-if="cible(p) && c in p.donnees && texte(avant(p, c)) !== texte(p.donnees[c])" class="avant-apres">
            <em>{{ c }}</em>
            <del>{{ texte(avant(p, c)) }}</del>
            <ins>{{ texte(p.donnees[c]) }}</ins>
          </div>
        </template>
        <p v-if="p.donnees.raison">Raison : {{ p.donnees.raison }}</p>
      </template>
      <template v-else>
        <strong>Retrait de #{{ p.tache_id }}{{ cible(p) ? ` (${cible(p)!.titre})` : '' }}</strong>
        <p>Raison : {{ p.donnees.raison }}</p>
      </template>
      <div class="actions">
        <button class="primaire" @click="emit('accepter', p)">Accepter</button>
        <button v-if="p.sorte !== 'retrait'" @click="emit('modifier', p)">Modifier puis accepter</button>
        <button class="danger" @click="emit('rejeter', p)">Rejeter</button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.panneau { display: flex; flex-direction: column; gap: 0.5rem; }
.prop { border: 1px solid var(--alerte); background: var(--jaune-doux); border-radius: var(--rayon); padding: 0.75rem 1rem; }
.prop ul { margin: 0.25rem 0; padding-left: 1.25rem; }
.avant-apres { display: flex; flex-direction: column; white-space: pre-wrap; }
del { color: var(--danger); }
ins { color: var(--succes); text-decoration: none; }
.actions { display: flex; gap: 0.4rem; margin-top: 0.5rem; }
</style>
