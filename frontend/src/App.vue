<template>
  <header>
    <strong>Portail</strong>
    <RouterLink to="/">Pipelines</RouterLink>
    <RouterLink to="/projets">Projets</RouterLink>
  </header>
  <main><RouterView /></main>
</template>

<style>
body { font-family: system-ui, sans-serif; margin: 0; color: #222; }
header { display: flex; gap: 1rem; align-items: center; padding: 0.75rem 1.5rem; background: #f3f4f6; border-bottom: 1px solid #ddd; }
main { max-width: 64rem; margin: 1rem auto; padding: 0 1.5rem; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; }
input, select, textarea, button { font: inherit; padding: 0.3rem 0.5rem; }
form { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 1rem 0; }
.erreur { color: #b91c1c; }
</style>
