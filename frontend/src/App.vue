<template>
  <header class="entete">
    <RouterLink to="/" class="marque">Portail</RouterLink>
    <nav>
      <RouterLink to="/">Pipelines</RouterLink>
      <RouterLink to="/projets">Projets</RouterLink>
      <RouterLink to="/chat">Chat</RouterLink>
      <RouterLink to="/audit">Audit</RouterLink>
    </nav>
  </header>
  <main :class="{ large: $route.name === 'kanban' }"><RouterView /></main>
</template>
