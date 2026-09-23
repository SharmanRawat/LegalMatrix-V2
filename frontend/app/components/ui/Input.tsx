import { InputHTMLAttributes, forwardRef } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Icon element to display on the left */
  icon?: React.ReactNode
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ icon, className = '', ...props }, ref) => {
    return (
      <div className="relative">
        {icon && (
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none">
            {icon}
          </span>
        )}
        <input
          ref={ref}
          className={`glass-input ${icon ? 'pl-10' : ''} ${className}`}
          {...props}
        />
      </div>
    )
  }
)

Input.displayName = 'Input'

export default Input
