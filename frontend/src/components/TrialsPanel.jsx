import { useState, useEffect } from 'react'
import { fetchCompanyTrials } from '../api'
import { eventColor } from '../parseWiki'

const ACTIVE_COLOR    = '#1D9E75'
const COMPLETED_COLOR = '#aaa'

function StatCard({ label, value }) {
  return (
    <div style={{
      background: '#f5f4f0',
      borderRadius: 10,
      padding: '14px 18px',
      flex: 1,
    }}>
      <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: '#1a1a18', lineHeight: 1 }}>{value}</div>
    </div>
  )
}

function PhaseChart({ phases }) {
  if (!phases.length) return null

  const maxVal = Math.max(...phases.flatMap(p => [p.active, p.completed]), 1)
  const BAR_H   = 14
  const GAP     = 5
  const ROW_H   = BAR_H * 2 + GAP + 16  // two bars + gap + phase label spacing
  const LABEL_W = 110
  const CHART_W = 260
  const totalH  = phases.length * ROW_H

  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', gap: 16, marginBottom: 10, fontSize: 11, color: '#666' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: ACTIVE_COLOR, display: 'inline-block' }} />
          Active / recruiting
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: COMPLETED_COLOR, display: 'inline-block' }} />
          Reached primary completion
        </span>
      </div>

      <svg width="100%" viewBox={`0 0 ${LABEL_W + CHART_W} ${totalH}`} style={{ overflow: 'visible' }}>
        {phases.map((p, i) => {
          const y        = i * ROW_H
          const activeW  = (p.active    / maxVal) * CHART_W
          const compW    = (p.completed / maxVal) * CHART_W

          return (
            <g key={p.phase}>
              <text x={LABEL_W - 8} y={y + BAR_H - 2} textAnchor="end" fontSize={11} fill="#666">
                {p.phase}
              </text>

              {/* active bar */}
              {p.active > 0 && (
                <rect x={LABEL_W} y={y} width={activeW} height={BAR_H} rx={3} fill={ACTIVE_COLOR} />
              )}

              {/* completed bar */}
              {p.completed > 0 && (
                <rect x={LABEL_W} y={y + BAR_H + GAP} width={compW} height={BAR_H} rx={3} fill={COMPLETED_COLOR} />
              )}

              {/* count labels */}
              {p.active > 0 && (
                <text x={LABEL_W + activeW + 5} y={y + BAR_H - 2} fontSize={10} fill="#555">{p.active}</text>
              )}
              {p.completed > 0 && (
                <text x={LABEL_W + compW + 5} y={y + BAR_H + GAP + BAR_H - 2} fontSize={10} fill="#555">{p.completed}</text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

export default function TrialsPanel({ slug, researchEvents, recentCompletions }) {
  const [trialsData, setTrialsData] = useState(null)

  useEffect(() => {
    setTrialsData(null)
    fetchCompanyTrials(slug).then(setTrialsData)
  }, [slug])

  if (!trialsData) return null

  const { stats, phases } = trialsData
  // Supplement trials-wiki completed count with event-table completions
  // (completed trials aren't always in the trials wiki if they were only
  //  captured as events during pipeline processing)
  const completedCount = Math.max(stats.completed_90d, recentCompletions ?? 0)
  const hasTrialData  = phases.length > 0
  const hasResearch   = researchEvents.length > 0

  if (!hasTrialData && !hasResearch) return null

  return (
    <div className="card">
      <p className="sec-label" style={{ marginBottom: 12 }}>Clinical evidence</p>

      {hasTrialData && (
        <>
          {/* Stat cards */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <StatCard label="Active trials"           value={stats.active} />
            <StatCard label="Reached completion (1y)" value={completedCount} />
            <StatCard label="With published results"  value={stats.with_results} />
          </div>

          {/* Phase chart */}
          <PhaseChart phases={phases} />
        </>
      )}

      {/* Clinical findings from pubmed */}
      {hasResearch && (
        <>
          {hasTrialData && <hr className="divider" style={{ margin: '16px 0' }} />}
          <p className="sec-label" style={{ marginBottom: 10 }}>Published results</p>
          <div className="event-list">
            {researchEvents.slice(0, 5).map((e, i) => (
              <div key={i} className="event-row">
                <span className="evt-dot" style={{ background: eventColor(e.event) }} />
                <div>
                  <div className="evt-date">{e.date}</div>
                  <div className="evt-text">{e.event}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
