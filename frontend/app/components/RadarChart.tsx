'use client'

import { RadarResult } from '@/app/lib/api'

const GRADE_COLORS: Record<string, string> = {
  A: '#16a34a',
  B: '#eab308',
  C: '#f97316',
  D: '#dc2626',
}

export default function RadarChart({ radar, size = 280 }: { radar: RadarResult; size?: number }) {
  const axes = radar.axes ?? []
  const n = axes.length
  if (n === 0) return null

  const cx = size / 2
  const cy = size / 2
  const maxR = size / 2 - 42
  const angle = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / n
  const pt = (i: number, v: number) => {
    const r = (v / 100) * maxR
    return [cx + r * Math.cos(angle(i)), cy + r * Math.sin(angle(i))] as const
  }

  const rings = [20, 40, 60, 80, 100]
  const ringPoints = (value: number) =>
    axes.map((_, i) => pt(i, value).join(',')).join(' ')

  const valuePoints = axes.map((a, i) => pt(i, a.score ?? 0)).join(' ')
  const hasValues = axes.some((a) => a.score !== null)
  const overall = radar.overall
  const gradSkill = overall >= 80 ? 'A' : overall >= 50 ? 'B' : 'C'
  const color = GRADE_COLORS[radar.grade] ?? GRADE_COLORS[gradSkill] ?? '#2563eb'

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} className="max-w-full h-auto" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Compliance radar chart">
        {rings.map((v) => (
          <polygon
            key={v}
            points={ringPoints(v)}
            fill="none"
            stroke="#e5e7eb"
            strokeWidth={v === 100 ? 1.2 : 0.8}
          />
        ))}

        {axes.map((a, i) => {
          const [x, y] = pt(i, 108)
          const label = a.axis.length > 12 ? a.axis.replace(/ /g, '\n') : a.axis
          return (
            <g key={a.axis}>
              <line x1={cx} y1={cy} x2={pt(i, 100)[0]} y2={pt(i, 100)[1]} stroke="#f3f4f6" strokeWidth={1} />
              <text
                x={x}
                y={y}
                textAnchor="middle"
                dominantBaseline="middle"
                className="fill-gray-500 text-[10px] font-medium"
              >
                {label.split('\n').map((line, li) => (
                  <tspan key={li} x={x} dy={li === 0 ? -4 : 11}>
                    {line}
                  </tspan>
                ))}
              </text>
              {a.score !== null ? (
                <text x={pt(i, a.score)[0]} y={pt(i, a.score)[1] - 8} textAnchor="middle" className="fill-gray-700 text-[10px] font-semibold">
                  {Math.round(a.score)}
                </text>
              ) : (
                <text x={pt(i, 8)[0]} y={pt(i, 8)[1]} textAnchor="middle" className="fill-gray-400 text-[9px]">
                  n/a
                </text>
              )}
            </g>
          )
        })}

        {hasValues && (
          <polygon
            points={valuePoints}
            fill={color}
            fillOpacity={0.18}
            stroke={color}
            strokeWidth={2}
            strokeLinejoin="round"
          />
        )}
      </svg>

      <div className="mt-1 flex items-center gap-3">
        <span
          className="px-3 py-1 rounded-lg text-white text-sm font-bold"
          style={{ backgroundColor: color }}
        >
          Grade {radar.grade}
        </span>
        <span className="text-sm text-gray-600">Overall {Math.round(overall)}%</span>
        <span className="text-xs text-gray-400">{radar.grade_label}</span>
      </div>
    </div>
  )
}