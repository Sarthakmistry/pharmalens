import { useState, useEffect } from 'react'
import { fetchCompanyTrials } from '../api'
import { eventColor } from '../parseWiki'

const ACTIVE_COLOR    = '#4d9ef7'
const COMPLETED_COLOR = '#3a4560'

function StatCard({ label, value }) {
  return (
    <div style={{
      background: '#1a2035',
      borderRadius: 8,
      padding: '10px 12px',
      flex: 1,
    }}>
      <div style={{ fontSize: 11, color: '#7a8099', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: '#dde1f0', lineHeight: 1 }}>{value}</div>
    </div>
  )
}

function PhaseChart({ phases }) {
  if (!phases.length) return null

  const maxVal  = Math.max(...phases.flatMap(p => [p.active, p.completed]), 1)
  const BAR_H   = 10
  const GAP     = 4
  const ROW_H   = BAR_H * 2 + GAP + 12
  const LABEL_W = 80
  const CHART_W = 220
  const COUNT_W = 28
  const TOTAL_W = LABEL_W + CHART_W + COUNT_W
  const totalH  = phases.length * ROW_H

  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 8, fontSize: 10, color: '#7a8099' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: ACTIVE_COLOR, display: 'inline-block' }} />
          Active / recruiting
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: COMPLETED_COLOR, display: 'inline-block' }} />
          Reached primary completion
        </span>
      </div>

      <svg width={TOTAL_W} viewBox={`0 0 ${TOTAL_W} ${totalH}`}>
        {phases.map((p, i) => {
          const y       = i * ROW_H
          const activeW = (p.active    / maxVal) * CHART_W
          const compW   = (p.completed / maxVal) * CHART_W

          return (
            <g key={p.phase}>
              <text x={LABEL_W - 6} y={y + BAR_H - 1} textAnchor="end" fontSize={11} fill="#9aa3be">
                {p.phase}
              </text>

              {p.active > 0 && (
                <rect x={LABEL_W} y={y} width={activeW} height={BAR_H} rx={2} fill={ACTIVE_COLOR} />
              )}
              {p.completed > 0 && (
                <rect x={LABEL_W} y={y + BAR_H + GAP} width={compW} height={BAR_H} rx={2} fill={COMPLETED_COLOR} />
              )}

              {p.active > 0 && (
                <text x={LABEL_W + activeW + 5} y={y + BAR_H - 1} fontSize={10} fill="#9aa3be">{p.active}</text>
              )}
              {p.completed > 0 && (
                <text x={LABEL_W + compW + 5} y={y + BAR_H + GAP + BAR_H - 1} fontSize={10} fill="#9aa3be">{p.completed}</text>
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
