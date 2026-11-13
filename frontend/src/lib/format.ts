const DATE_FMT = new Intl.DateTimeFormat('fr-FR', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
})

/** « 2026-12-05 » → « Samedi 5 décembre » */
export function formatDay(day: string): string {
  const text = DATE_FMT.format(new Date(`${day}T12:00:00`))
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Lendemain d'une date AAAA-MM-JJ (ou aujourd'hui si absente). */
export function nextDay(day: string | undefined): string {
  const base = day ? new Date(`${day}T12:00:00`) : new Date()
  return new Date(base.getTime() + (day ? 86_400_000 : 0)).toISOString().slice(0, 10)
}
