import { HTMLAttributes, forwardRef } from 'react'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** No border — flat glass surface */
  flat?: boolean
  /** Extra padding */
  padding?: 'sm' | 'md' | 'lg'
}

const paddingClasses = {
  sm: 'p-4',
  md: 'p-5',
  lg: 'p-6',
}

const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ flat, padding = 'md', className = '', children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={`${flat ? 'glass' : 'glass-card'} ${paddingClasses[padding]} ${className}`}
        {...props}
      >
        {children}
      </div>
    )
  }
)

Card.displayName = 'Card'

export default Card
