import { useState, useEffect, useRef, useCallback } from 'react'
import * as d3 from 'd3'
import { fetchCompanyTrials } from '../api'
import { eventColor } from '../parseWiki'

const ACTIVE_COLOR    = '#4d9ef7'
const COMPLETED_COLOR = '#3a4560'

const MARGIN  = { top: 4, right: 36, bottom: 20, left: 72 }
const BAR_H   = 13
const BAR_GAP = 8

// Some wiki entries have the literal string "None"/"N/A"/"null" instead of a real null —
// treat those as missing.
const isRealValue = v => v && v.trim() && !/^(none|n\/a|null)$/i.test(v.trim())

function StatCard({ label, value, sub }) {
  return (
    <div style={{
      background: '#1a2035',
      borderRadius: 8,
      padding: '10px 12px',
      flex: 1,
    }}>
      <div style={{ fontSize: 11, color: '#7a8099', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 500, color: '#dde1f0', lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: '#7a8099', marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

function PhaseChart({ phases }) {
  const svgRef  = useRef(null)
  const wrapRef = useRef(null)

  const draw = useCallback(() => {
    if (!phases.length || !svgRef.current || !wrapRef.current) return

    const W  = wrapRef.current.clientWidth
    const nR = phases.length
    const H  = MARGIN.top + nR * (BAR_H + BAR_GAP) - BAR_GAP + MARGIN.bottom
    const iW = W - MARGIN.left - MARGIN.right

    const maxVal = Math.max(...phases.map(p => p.active + p.completed), 1)
    const xScale = d3.scaleLinear().domain([0, maxVal]).range([0, iW])

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    svg.attr('width', W).attr('height', H)

    const g = svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

    // X axis
    g.append('g')
      .attr('transform', `translate(0,${H - MARGIN.top - MARGIN.bottom})`)
      .call(d3.axisBottom(xScale).ticks(4).tickSize(-(H - MARGIN.top - MARGIN.bottom)).tickFormat(d3.format('d')))
      .call(ax => ax.select('.domain').remove())
      .call(ax => ax.selectAll('text').attr('font-size', 10).attr('fill', '#7a8099'))
      .call(ax => ax.selectAll('.tick line').attr('stroke', '#252b3b').attr('stroke-dasharray', '3 2'))

    phases.forEach((p, i) => {
      const y      = i * (BAR_H + BAR_GAP)
      const aW     = xScale(p.active)
      const cW     = xScale(p.completed)
      const total  = p.active + p.completed

      // Phase label
      g.append('text')
        .attr('x', -6).attr('y', y + BAR_H / 2 + 4)
        .attr('text-anchor', 'end')
        .attr('font-size', 11).attr('fill', '#9aa3be')
        .text(p.phase)

      // Active segment
      if (p.active > 0) {
        g.append('rect')
          .attr('x', 0).attr('y', y)
          .attr('width', aW).attr('height', BAR_H)
          .attr('rx', 2).attr('fill', ACTIVE_COLOR)
      }

      // Completed segment (stacked)
      if (p.completed > 0) {
        g.append('rect')
          .attr('x', aW).attr('y', y)
          .attr('width', cW).attr('height', BAR_H)
          .attr('rx', 2).attr('fill', COMPLETED_COLOR)
      }

      // Total count at end
      if (total > 0) {
        g.append('text')
          .attr('x', aW + cW + 5).attr('y', y + BAR_H / 2 + 4)
          .attr('font-size', 10).attr('fill', '#7a8099')
          .text(total)
      }
    })
  }, [phases])

  useEffect(() => {
    draw()
    const ro = new ResizeObserver(draw)
    if (wrapRef.current) ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [draw])

  if (!phases.length) return null

  return (
    <div ref={wrapRef} style={{ width: '100%', marginTop: 10 }}>
      <div style={{ display: 'flex', gap: 14, marginBottom: 8, fontSize: 10, color: '#7a8099' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: ACTIVE_COLOR, display: 'inline-block' }} />
          Active / recruiting
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: COMPLETED_COLOR, display: 'inline-block' }} />
          Reached primary completion
        </span>
      </div>
      <svg ref={svgRef} style={{ display: 'block', overflow: 'visible' }} />
    </div>
  )
}

function TrialResultCard({ trial }) {
  const [open, setOpen] = useState(false)
  const cf = trial.clinical_findings || {}
  const hasDetail = cf.study_design || cf.sample_size || cf.comparator || cf.secondary_results || cf.safety_note

  return (
    <div style={{ borderTop: '1px solid #252b3b', paddingTop: 10, marginTop: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 10, color: '#7a8099', marginBottom: 3 }}>
            {trial.trial_id && (
              <a
                href={`https://clinicaltrials.gov/study/${trial.trial_id}`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: '#4d9ef7', textDecoration: 'none' }}
              >
                {trial.trial_id}
              </a>
            )}
            {trial.primary_completion_date ? ` · ${trial.primary_completion_date}` : ''}{cf.journal ? ` · ${cf.journal}` : ''}
            {cf.publication_year && !cf.journal ? ` · ${cf.publication_year}` : ''}
          </div>
          <div style={{ fontSize: 11, color: '#c8cee0', fontWeight: 500, marginBottom: 4 }}>
            {Array.isArray(trial.drugs) ? trial.drugs.join(', ') : (trial.drugs || '')}
            {trial.indications?.length ? ` — ${trial.indications.join(', ')}` : ''}
          </div>
          {isRealValue(trial.result_summary) && (
            <div style={{ fontSize: 11, color: '#dde1f0', lineHeight: 1.5, marginBottom: 3 }}>
              {trial.result_summary}
            </div>
          )}
          <div style={{ fontSize: 11, color: '#9aa3be', lineHeight: 1.5 }}>
            {trial.primary_result_value}
          </div>
        </div>
        {hasDetail && (
          <button
            onClick={() => setOpen(v => !v)}
            style={{ fontSize: 10, color: '#4d9ef7', background: 'none', border: 'none', cursor: 'pointer', padding: 0, flexShrink: 0, marginTop: 2 }}
          >
            {open ? 'less' : 'details'}
          </button>
        )}
      </div>

      {open && hasDetail && (
        <div style={{ marginTop: 8, fontSize: 10, color: '#9aa3be', lineHeight: 1.6, display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 10px' }}>
          {cf.study_design  && <><span style={{ color: '#7a8099' }}>Design</span><span>{cf.study_design}</span></>}
          {cf.sample_size   && <><span style={{ color: '#7a8099' }}>N</span><span>{cf.sample_size}</span></>}
          {cf.comparator    && <><span style={{ color: '#7a8099' }}>vs</span><span>{cf.comparator}</span></>}
          {cf.secondary_results && <><span style={{ color: '#7a8099' }}>Secondary</span><span>{cf.secondary_results}</span></>}
          {cf.safety_note   && <><span style={{ color: '#7a8099' }}>Safety</span><span>{cf.safety_note}</span></>}
        </div>
      )}
    </div>
  )
}

export default function TrialsPanel({ slug, researchEvents, recentCompletions }) {
  const [trialsData, setTrialsData] = useState(null)
  const [showAllResults, setShowAllResults] = useState(false)
  const [showAllTrialResults, setShowAllTrialResults] = useState(false)

  useEffect(() => {
    setTrialsData(null)
    setShowAllResults(false)
    setShowAllTrialResults(false)
    fetchCompanyTrials(slug).then(setTrialsData)
  }, [slug])

  if (!trialsData) return null

  const { stats, phases, trials = [] } = trialsData
  const completedCount = Math.max(stats.completed_90d, recentCompletions ?? 0)
  const hasTrialData   = phases.length > 0
  const hasResearch    = researchEvents.length > 0

  // Trials with a published result value, sorted newest completion date first.
  const trialResults = trials
    .filter(t => t.has_results && isRealValue(t.primary_result_value))
    .sort((a, b) => (b.primary_completion_date || '').localeCompare(a.primary_completion_date || ''))
  const hasTrialResults  = trialResults.length > 0
  const visibleTrialResults = showAllTrialResults ? trialResults : trialResults.slice(0, 2)

  if (!hasTrialData && !hasResearch && !hasTrialResults) return null

  const visibleResults = showAllResults ? researchEvents : researchEvents.slice(0, 1)

  return (
    <div className="card">
      <p className="sec-label" style={{ marginBottom: 12 }}>Clinical evidence</p>

      {hasTrialData && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <StatCard label="Active trials"        value={stats.active} />
            <StatCard label="Reached completion"   value={completedCount} sub="last 12 months" />
            <StatCard label="Published results"    value={stats.with_results} />
          </div>
          <PhaseChart phases={phases} />
        </>
      )}

      {hasTrialResults && (
        <>
          <hr className="divider" style={{ margin: '14px 0' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
            <p className="sec-label" style={{ margin: 0 }}>Trial results</p>
            {trialResults.length > 2 && (
              <button
                onClick={() => setShowAllTrialResults(v => !v)}
                style={{ fontSize: 11, color: '#4d9ef7', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
              >
                {showAllTrialResults ? 'show less' : `+${trialResults.length - 2} more`}
              </button>
            )}
          </div>
          {visibleTrialResults.map((t, i) => (
            <TrialResultCard key={t.trial_id || i} trial={t} />
          ))}
        </>
      )}

      {hasResearch && (
        <>
          <hr className="divider" style={{ margin: '14px 0' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
            <p className="sec-label" style={{ margin: 0 }}>
              {showAllResults ? 'Published research' : 'Latest published research'}
            </p>
            {researchEvents.length > 1 && (
              <button
                onClick={() => setShowAllResults(v => !v)}
                style={{ fontSize: 11, color: '#4d9ef7', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
              >
                {showAllResults ? 'show less' : `+${researchEvents.length - 1} more`}
              </button>
            )}
          </div>
          <div className="event-list">
            {visibleResults.map((e, i) => {
              // Older wiki entries embed the sentiment word in the text itself
              // (e.g. "Bullish pubmed result for..."); strip it so we don't double up.
              const text = e.event.replace(/^(moderately\s+)?(bullish|bearish|neutral)\s+/i, '')
              const pmid = /^PMID:\s*(\d+)/i.exec(e.source || '')?.[1]
              return (
                <div key={i} className="event-row">
                  <span className="evt-dot" style={{ background: eventColor(e.event) }} />
                  <div>
                    <div className="evt-date">
                      {e.date}
                      {pmid && (
                        <>
                          {' · '}
                          <a
                            href={`https://pubmed.ncbi.nlm.nih.gov/${pmid}/`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: '#4d9ef7', textDecoration: 'none' }}
                          >
                            PMID:{pmid}
                          </a>
                        </>
                      )}
                    </div>
                    <div className="evt-text">{text}</div>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
