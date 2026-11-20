import { useState, type ReactNode } from 'react'

export function Section({
  title,
  hint,
  description,
  defaultOpen = true,
  children,
}: {
  title: string
  hint?: string
  description?: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <details
      className="section"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <span className="section-label">
          <span className="section-title">{title}</span>
          {description && <span className="section-description">{description}</span>}
        </span>
        <span className="section-meta">
          {hint && <span className="section-hint">{hint}</span>}
          <svg
            className="section-chevron"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            aria-hidden="true"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
      </summary>
      <div className="section-body">{children}</div>
    </details>
  )
}
