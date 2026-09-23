import { HTMLAttributes } from 'react'

interface PageHeaderProps extends HTMLAttributes<HTMLDivElement> {
  title: string
  description?: string
  /** Right-side action (button, link, etc.) */
  action?: React.ReactNode
}

export default function PageHeader({ title, description, action, className = '', ...props }: PageHeaderProps) {
  return (
    <div className={`flex items-start justify-between gap-4 ${className}`} {...props}>
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-text-primary">{title}</h1>
        {description && (
          <p className="text-sm text-text-secondary mt-1">{description}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}
