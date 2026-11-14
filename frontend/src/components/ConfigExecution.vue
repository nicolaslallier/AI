<script setup lang="ts">
import { ref } from 'vue'
import { definirExecution } from '../api'

const props = defineProps<{ projetId: number; config: string | null }>()
const emit = defineEmits<{ enregistre: [] }>()

// Exemple en commentaires : l'enregistrer tel quel n'active rien (422), il faut le décommenter.
const EXEMPLE = `# Décommentez et adaptez, puis enregistrez.
# image: ghcr.io/nicolaslallier/ai-execution:latest
# chemins_tests: ["backend/tests/**", "frontend/**/*.spec.ts"]
# commandes:
#   installer: "cd backend && uv sync"
#   tests: "cd backend && uv run pytest"
#   tests_cibles: "cd backend && uv run pytest {fichiers}"
# services:
#   - nom: postgres
#     image: "pgvector/pgvector:pg16"
#     env: {POSTGRES_PASSWORD: test}
`
const yaml = ref(props.config || EXEMPLE)
const erreur = ref('')
const ok = ref(false)

async function enregistrer() {
  erreur.value = ''
  ok.value = false
  try {
    await definirExecution(props.projetId, yaml.value)
    ok.value = true
    emit('enregistre')
  } catch (e) {
    erreur.value = (e as Error).message // un 422 porte son detail
  }
}
</script>

<template>
  <form class="pile" @submit.prevent="enregistrer">
    <textarea v-model="yaml" rows="14" spellcheck="false" aria-label="Configuration d'exécution (YAML)"></textarea>
    <div><button>Enregistrer</button></div>
    <p v-if="erreur" class="erreur">{{ erreur }}</p>
    <p v-if="ok" class="discret">Configuration enregistrée.</p>
  </form>
</template>
