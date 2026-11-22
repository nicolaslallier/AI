// Sépare le frontmatter YAML (entre deux lignes `---` en tête) du corps de la note.
export function separerFrontmatter(md: string): { frontmatter: string; corps: string } {
  const m = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/.exec(md)
  return m ? { frontmatter: m[1], corps: md.slice(m[0].length) } : { frontmatter: '', corps: md }
}
