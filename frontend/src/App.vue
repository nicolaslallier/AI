<template>
  <header class="entete">
    <RouterLink to="/" class="marque">Portail</RouterLink>
    <nav>
      <RouterLink to="/">Pipelines</RouterLink>
      <RouterLink to="/projets">Projets</RouterLink>
    </nav>
  </header>
  <main :class="{ large: $route.name === 'kanban' }"><RouterView /></main>
</template>
