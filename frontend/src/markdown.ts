import DOMPurify from 'dompurify'
import { marked } from 'marked'

export function rendreMarkdown(texte: string): string {
  return DOMPurify.sanitize(marked.parse(texte, { async: false }) as string)
}

// Retire le dernier bloc ```json (le modèle ArchiMate en fin de document) pour l'affichage.
export function sansBlocModele(md: string): string {
  const debut = md.lastIndexOf('```json')
  if (debut < 0) return md
  const fin = md.indexOf('```', debut + 7)
  if (fin < 0) return md
  const apres = md.indexOf('\n', fin)
  return (md.slice(0, debut) + (apres < 0 ? '' : md.slice(apres + 1))).trimEnd()
}
