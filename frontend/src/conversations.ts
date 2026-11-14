import type { ConversationResume } from './api'

export function trier(liste: ConversationResume[]): ConversationResume[] {
  return [...liste].sort((a, b) => b.maj_le.localeCompare(a.maj_le))
}
