import { useState, useEffect } from 'react'
import { fetchCompany } from '../api'
import { parseEventsTable, eventColor } from '../parseWiki'
import AIBar from './AIBar'


export default function CompanyView({ slug, onSelectIndication }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    setData(null)
    fetchCompany(slug).then(d => { setData(d); setLoading(false) })
  }, [slug])

  if (loading) return <div className="loading">Loading {slug}…</div>
  if (!data) return null

  const { meta, wiki, stock, drug_indications = {} } = data
  const events = parseEventsTable(wiki)
  const secEvents   = events.filter(e => e.type === 'sec')
  const trialEvents = events.filter(e => e.type === 'trial' || e.type === 'research')

  const changePct = stock?.change_pct
  const priceClass = changePct > 0 ? 'price-pos' : changePct < 0 ? 'price-neg' : 'price-neu'

  const fmtIndication = slug =>
    slug.replace('glp1', 'GLP-1').replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

  return (
    <div>
      {/* Company header */}
      <div className="ind-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <h1 className="ind-title">{meta.full_name}</h1>
          {stock?.price != null && (
            <span className={priceClass} style={{ fontSize: 16, fontWeight: 500 }}>
              {meta.ticker} ${stock.price.toFixed(2)}&nbsp;
              ({changePct > 0 ? '+' : ''}{changePct?.toFixed(2)}%)
            </span>
          )}
        </div>
        <div className="ind-meta">
          <span className="chip">{meta.exchange ?? 'NYSE'}</span>
          {meta.headquarters && <span className="chip">{meta.headquarters}</span>}
          {meta.indications_active?.length > 0 && (
            <span className="chip">{meta.indications_active.length} indications</span>
          )}
          {meta.drugs?.length > 0 && (
            <span className="chip">{meta.drugs.length} drugs</span>
          )}
        </div>
      </div>

      {/* Drug portfolio */}
      {meta.drugs?.length > 0 && (
        <>
          <p className="sec-label" style={{ marginBottom: 10 }}>Drug portfolio</p>
          <div className="drug-grid" style={{ marginBottom: 20 }}>
            {meta.drugs.map((drug, i) => {
              const indications = drug_indications[drug] ?? []
              return (
                <div key={i} className="drug-card">
                  <div className="drug-name">{drug}</div>
                  {indications.length > 0 && (
                    <div className="drug-co" style={{ marginBottom: 8 }}>
                      {indications.map(fmtIndication).join(' · ')}
                    </div>
                  )}
                  <span className="badge badge-approved">Active</span>
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* Events + indications in one row */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${[secEvents.length > 0, true, meta.indications_active?.length > 0].filter(Boolean).length}, 1fr)`,
        gap: 10,
        marginBottom: 20,
        alignItems: 'start',
      }}>
        {secEvents.length > 0 && (
          <div className="card">
            <p className="sec-label" style={{ marginBottom: 12 }}>Earnings &amp; regulatory</p>
            <div className="event-list">
              {secEvents.slice(0, 8).map((e, i) => (
                <div key={i} className="event-row">
                  <span className="evt-dot" style={{ background: eventColor(e.event) }} />
                  <div>
                    <div className="evt-date">{e.date}</div>
                    <div className="evt-text">{e.event}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="card">
          <p className="sec-label" style={{ marginBottom: 12 }}>Clinical trials</p>
          <div className="event-list">
            {trialEvents.length === 0 && (
              <p style={{ fontSize: 13, color: '#888780' }}>No trial events in wiki</p>
            )}
            {trialEvents.slice(0, 8).map((e, i) => (
              <div key={i} className="event-row">
                <span className="evt-dot" style={{ background: eventColor(e.event) }} />
                <div>
                  <div className="evt-date">{e.date}</div>
                  <div className="evt-text">{e.event}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {meta.indications_active?.length > 0 && (
          <div className="card">
            <p className="sec-label" style={{ marginBottom: 12 }}>Active indications</p>
            <div className="co-list">
              {meta.indications_active.map((ind, i) => (
                <div key={ind}>
                  {i > 0 && <hr className="divider" style={{ margin: 0 }} />}
                  <div
                    className="co-row"
                    style={{ cursor: onSelectIndication ? 'pointer' : 'default' }}
                    onClick={() => onSelectIndication?.(ind)}
                  >
                    <div className="co-name">{fmtIndication(ind)}</div>
                    <span className="badge badge-approved" style={{ fontSize: 11 }}>Active</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* AI bar */}
      <AIBar company={slug} displayName={meta.full_name} />
    </div>
  )
}
