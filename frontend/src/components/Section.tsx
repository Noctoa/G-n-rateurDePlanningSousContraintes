import type { ReactNode } from 'react'

export function Section({
  title,
  hint,
  defaultOpen = true,
  children,
}: {
  title: string
  hint?: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  return (
    <details className="section" open={defaultOpen}>
      <summary>
        <span className="section-title">{title}</span>
        {hint && <span className="section-hint">{hint}</span>}
      </summary>
      <div className="section-body">{children}</div>
    </details>
  )
}
