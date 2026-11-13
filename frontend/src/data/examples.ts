// Jeux de données d'exemple, importés directement depuis /datasets (cf. vite.config.ts).
import type { Tournament } from '../api/client.ts'
import medium from '../../../datasets/medium.json'
import small from '../../../datasets/small.json'
import unsolvable from '../../../datasets/unsolvable.json'

export const EXAMPLES: { key: string; label: string; tournament: Tournament }[] = [
  { key: 'small', label: 'Petit — 6 équipes', tournament: small as Tournament },
  { key: 'medium', label: 'Moyen — 16 équipes en 2 poules', tournament: medium as Tournament },
  { key: 'unsolvable', label: 'Insoluble (volontairement)', tournament: unsolvable as Tournament },
]
