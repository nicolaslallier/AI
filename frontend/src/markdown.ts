import DOMPurify from 'dompurify'
import { marked } from 'marked'

export function rendreMarkdown(texte: string): string {
  return DOMPurify.sanitize(marked.parse(texte, { async: false }) as string)
}

// Retire le dernier bloc ```json (le modèle ArchiMate en fin de document) pour l'affichage.
// Seule une clôture qui commence une ligne compte ; un bloc non refermé reste tel quel.
export function sansBlocModele(md: string): string {
  const ouvertures = [...md.matchAll(/^```json[ \t]*\r?$/gm)]
  const debut = ouvertures.at(-1)?.index
  if (debut === undefined) return md
  const fermeture = /^```[ \t]*\r?$/m.exec(md.slice(debut + 7))
  if (!fermeture) return md
  const fin = debut + 7 + fermeture.index + fermeture[0].length
  return (md.slice(0, debut) + md.slice(fin)).trimEnd()
}
