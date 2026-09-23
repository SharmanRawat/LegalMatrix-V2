import { HTMLAttributes, forwardRef } from 'react'

type Variant = 'success' | 'warning' | 'danger' | 'info'

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: Variant
}

const variantClasses: Record<Variant, string> = {
  success: 'badge-success',
  warning: 'badge-warning',
  danger: 'badge-danger',
  info: 'badge-info',
}

/** Map backend status strings to badge variants */
export function statusToVariant(status: string): Variant {
  switch (status) {
    case 'COMPLIANT':
      return 'success'
    case 'REVIEW_REQUIRED':
      return 'warning'
    case 'POTENTIAL_VIOLATION':
      return 'danger'
    default:
      return 'info'
  }
}

/** Format status string for display: "POTENTIAL_VIOLATION" → "Potential Violation" */
export function formatStatus(status: string): string {
  return status
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Compliance score → badge variant band (≥90 pass, ≥70 review, else fail) */
export function scoreToVariant(score: number): Variant {
  if (score >= 90) return 'success'
  if (score >= 70) return 'warning'
  return 'danger'
}

const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({ variant = 'info', className = '', children, ...props }, ref) => {
    return (
      <span
        ref={ref}
        className={`badge ${variantClasses[variant]} ${className}`}
        {...props}
      >
        {children}
      </span>
    )
  }
)

Badge.displayName = 'Badge'

export default Badge
