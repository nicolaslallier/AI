import { createRouter, createWebHistory } from 'vue-router'
import PipelinesView from './views/PipelinesView.vue'
import ProjetsView from './views/ProjetsView.vue'
import ProjetView from './views/ProjetView.vue'
import PipelineView from './views/PipelineView.vue'
import KanbanView from './views/KanbanView.vue'
import ChatView from './views/ChatView.vue'
import BureauView from './views/BureauView.vue'
import AuditView from './views/AuditView.vue'
import MusiqueView from './views/MusiqueView.vue'
import CoffreView from './views/CoffreView.vue'
import DocsView from './views/DocsView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'pipelines', component: PipelinesView },
    { path: '/projets', name: 'projets', component: ProjetsView },
    { path: '/projets/:id', name: 'projet', component: ProjetView, props: true },
    { path: '/projets/:id/kanban', name: 'kanban', component: KanbanView, props: true },
    { path: '/pipelines/:id', name: 'pipeline', component: PipelineView, props: true },
    { path: '/bureau', name: 'bureau', component: BureauView },
    { path: '/audit', name: 'audit', component: AuditView },
    { path: '/musique', name: 'musique', component: MusiqueView },
    { path: '/coffre', name: 'coffre', component: CoffreView },
    { path: '/docs', name: 'docs', component: DocsView },
    { path: '/chat', name: 'chat', component: ChatView },
    { path: '/chat/:id', name: 'conversation', component: ChatView, props: true },
  ],
})
