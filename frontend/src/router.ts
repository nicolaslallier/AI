import { createRouter, createWebHistory } from 'vue-router'
import PipelinesView from './views/PipelinesView.vue'
import ProjetsView from './views/ProjetsView.vue'
import ProjetView from './views/ProjetView.vue'
import PipelineView from './views/PipelineView.vue'
import KanbanView from './views/KanbanView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'pipelines', component: PipelinesView },
    { path: '/projets', name: 'projets', component: ProjetsView },
    { path: '/projets/:id', name: 'projet', component: ProjetView, props: true },
    { path: '/projets/:id/kanban', name: 'kanban', component: KanbanView, props: true },
    { path: '/pipelines/:id', name: 'pipeline', component: PipelineView, props: true },
  ],
})
