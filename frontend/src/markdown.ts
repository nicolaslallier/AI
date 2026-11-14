import DOMPurify from 'dompurify'
import { marked } from 'marked'

export function rendreMarkdown(texte: string): string {
  return DOMPurify.sanitize(marked.parse(texte, { async: false }) as string)
}
