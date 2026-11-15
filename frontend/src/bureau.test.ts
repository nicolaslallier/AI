import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, nextTick, type App } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Bureau, Poste } from './api'
import BureauView from './views/BureauView.vue'

vi.mock('./api', () => ({ lireBureau: vi.fn(), lirePoste: vi.fn() }))
import { lireBureau, lirePoste } from './api'

class FauxEventSource {
  static derniere: FauxEventSource
  close = vi.fn()
  ecouteurs: Record<string, () => void> = {}
  constructor(public url: string) {
    FauxEventSource.derniere = this
  }
  addEventListener(nom: string, f: () => void) {
    this.ecouteurs[nom] = f
  }
}

const poste = (nom: string, extra: Partial<Poste> = {}): Poste => ({
  nom, etat: 'libre', travaux: [], appels_jour: 0, jetons_jour: 0, ...extra,
})
const bureau: Bureau = {
  groupes: [
    { nom: 'chaine', agents: ['xx', 'yy'] },
    { nom: 'autre', agents: ['yy'] },
    { nom: null, agents: ['zz'] },
  ],
  postes: {
    xx: poste('xx', {
      etat: 'au_travail', appels_jour: 3, jetons_jour: 1500,
      travaux: [{ sorte: 'etape', etat: 'au_travail', libelle: 'T12', lien: '/pipelines/4', tour: 2,
        jauge: { utilises: 10, max: 100, ratio: 0.1, niveau: 'ok' } }],
    }),
    // sans tour ni jauge
    yy: poste('yy', { etat: 'en_attente',
      travaux: [{ sorte: 'conversation', etat: 'en_attente', libelle: 'conversation #5', lien: '/chat/5', tour: null, jauge: null }] }),
    zz: poste('zz'),
  },
}

let app: App
let racine: HTMLElement

async function monter() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:p(.*)*', component: { template: '<i/>' } }] })
  racine = document.createElement('div')
  document.body.append(racine)
  app = createApp(BureauView).use(router)
  app.mount(racine)
  await vi.advanceTimersByTimeAsync(0)
}

beforeEach(() => {
  vi.useFakeTimers()
  ;(globalThis as any).EventSource = FauxEventSource
  vi.mocked(lireBureau).mockReset().mockResolvedValue(bureau)
  vi.mocked(lirePoste).mockReset().mockResolvedValue({
    nom: 'xx', description: 'd', modele: 'mm', modele_si_meme: null, outils: ['o1'], tours_max: 5,
    contexte_max: 100, missions: [],
  })
})
afterEach(() => {
  app.unmount()
  racine.remove()
  vi.useRealTimers()
})

it('rend les groupes de la réponse, agents aux noms quelconques, groupe null générique', async () => {
  await monter()
  const titres = [...racine.querySelectorAll('h2')].map((h) => h.textContent)
  expect(titres).toEqual(['chaine', 'autre', 'Hors pipeline'])
  const groupes = [...racine.querySelectorAll('section.groupe')]
  expect(groupes[0].querySelectorAll('.fleche')).toHaveLength(1) // entre xx et yy
  expect(groupes[1].querySelectorAll('.fleche')).toHaveLength(0)
  expect(groupes[2].querySelectorAll('.fleche')).toHaveLength(0)
  // yy figure dans deux groupes
  expect(racine.querySelectorAll('.poste')).toHaveLength(4)
  expect(racine.textContent).toContain('en attente de Nicolas')
  const lien = racine.querySelector('a[href="/pipelines/4"]')!
  expect(lien.textContent).toBe('T12')
  expect(racine.textContent).toContain('tour 2')
  expect(racine.textContent).toContain('3 appels')
})

it('poste sans tour ni jauge : rien ne s’affiche, rien ne plante', async () => {
  await monter()
  const yy = racine.querySelectorAll('section.groupe')[1].querySelector('.poste')!
  expect(yy.textContent).not.toContain('tour')
  expect(yy.querySelector('.barre')).toBeNull()
  expect(yy.querySelector('a[href="/chat/5"]')).not.toBeNull()
})

it('regroupe les signaux bureau et pipelines en un seul rechargement par seconde', async () => {
  await monter()
  expect(lireBureau).toHaveBeenCalledTimes(1)
  for (let i = 0; i < 5; i++) FauxEventSource.derniere.ecouteurs.bureau()
  await vi.advanceTimersByTimeAsync(999)
  expect(lireBureau).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(2)
  expect(lireBureau).toHaveBeenCalledTimes(2)
  FauxEventSource.derniere.ecouteurs.pipelines()
  FauxEventSource.derniere.ecouteurs.bureau()
  await vi.advanceTimersByTimeAsync(1001)
  expect(lireBureau).toHaveBeenCalledTimes(3)
})

it('le signal pipelines recharge aussi', async () => {
  await monter()
  FauxEventSource.derniere.ecouteurs.pipelines()
  await vi.advanceTimersByTimeAsync(1001)
  expect(lireBureau).toHaveBeenCalledTimes(2)
})

it('un clic ouvre le détail, un second le ferme ; le détail suit les rechargements', async () => {
  await monter()
  const bouton = racine.querySelector('button.nom') as HTMLButtonElement
  bouton.click()
  await vi.advanceTimersByTimeAsync(0)
  expect(lirePoste).toHaveBeenCalledWith('xx')
  expect(racine.querySelector('.detail')!.textContent).toContain('o1')
  expect(bouton.getAttribute('aria-expanded')).toBe('true')
  FauxEventSource.derniere.ecouteurs.bureau()
  await vi.advanceTimersByTimeAsync(1001)
  expect(lirePoste).toHaveBeenCalledTimes(2)
  bouton.click()
  await nextTick()
  expect(racine.querySelector('.detail')).toBeNull()
})

it('démontage : flux fermé, plus de rechargement, même pour un signal déjà reçu', async () => {
  await monter()
  const source = FauxEventSource.derniere
  source.ecouteurs.bureau()
  app.unmount()
  expect(source.close).toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(120000)
  expect(lireBureau).toHaveBeenCalledTimes(1)
  app = createApp({ template: '<i/>' }) // pour afterEach
  app.mount(document.createElement('div'))
})

it('un poste ouvert qui disparaît du bureau ferme le détail', async () => {
  await monter()
  ;(racine.querySelector('button.nom') as HTMLButtonElement).click()
  await vi.advanceTimersByTimeAsync(0)
  expect(racine.querySelector('.detail')).not.toBeNull()
  const { xx, ...reste } = bureau.postes
  vi.mocked(lireBureau).mockResolvedValue({ groupes: [{ nom: null, agents: ['zz'] }], postes: reste })
  FauxEventSource.derniere.ecouteurs.bureau()
  await vi.advanceTimersByTimeAsync(1001)
  expect(racine.querySelector('.detail')).toBeNull()
  expect(lirePoste).toHaveBeenCalledTimes(1)
})

it('à l’ouverture le détail est amené en vue, pas aux rechargements ; aria-controls relie le bouton', async () => {
  const scroll = vi.fn()
  Element.prototype.scrollIntoView = scroll
  await monter()
  const bouton = racine.querySelector('button.nom') as HTMLButtonElement
  bouton.click()
  await vi.advanceTimersByTimeAsync(0)
  expect(scroll).toHaveBeenCalledTimes(1)
  expect(scroll).toHaveBeenCalledWith({ block: 'nearest' })
  const detail = racine.querySelector('.detail')!
  expect(bouton.getAttribute('aria-controls')).toBe(detail.id)
  expect(detail.hasAttribute('aria-live')).toBe(false)
  FauxEventSource.derniere.ecouteurs.bureau()
  await vi.advanceTimersByTimeAsync(1001)
  expect(scroll).toHaveBeenCalledTimes(1)
  delete (Element.prototype as any).scrollIntoView
})

it('lecture du bureau en échec : message affiché, postes déjà chargés conservés', async () => {
  await monter()
  vi.mocked(lireBureau).mockRejectedValue(new Error('panne bureau'))
  FauxEventSource.derniere.ecouteurs.bureau()
  await vi.advanceTimersByTimeAsync(1001)
  expect(racine.querySelector('.erreur')!.textContent).toBe('panne bureau')
  expect(racine.querySelectorAll('.poste')).toHaveLength(4)
})
