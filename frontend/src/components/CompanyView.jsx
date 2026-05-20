import { useState, useEffect } from 'react'
import { fetchCompany } from '../api'
import { parseEventsTable, eventColor } from '../parseWiki'
import AIBar from './AIBar'

const SearchIcon = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
    <circle cx="6.5" cy="6.5" r="5" stroke="#888780" strokeWidth="1.5" />
    <path d="M10.5 10.5L14 14" stroke="#888780" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
)

export default function CompanyView({ slug }) {
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

  const changePct = stock?.change_pct
  const priceClass = changePct > 0 ? 'price-pos' : changePct < 0 ? 'price-neg' : 'price-neu'

  const fmtIndication = slug =>
    slug.replace('glp1', 'GLP-1').replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

  return (
    <div>
      {/* Topbar */}
      <div className="topbar">
        <div className="search-bar">
          <SearchIcon />
          <input type="text" defaultValue={meta.full_name} key={slug} />
        </div>
        <button className="search-btn">Search</button>
      </div>

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

      {/* Events + indications */}
      <div className="bottom-grid">
        {/* Events */}
        <div className="card">
          <p className="sec-label" style={{ marginBottom: 12 }}>Recent events</p>
          <div className="event-list">
            {events.length === 0 && (
              <p style={{ fontSize: 13, color: '#888780' }}>No events found in wiki</p>
            )}
            {events.slice(0, 6).map((e, i) => (
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

        {/* Active indications */}
        <div className="card">
          <p className="sec-label" style={{ marginBottom: 12 }}>Active indications</p>
          <div className="co-list">
            {(meta.indications_active ?? []).map((ind, i) => (
              <div key={ind}>
                {i > 0 && <hr className="divider" style={{ margin: 0 }} />}
                <div className="co-row" style={{ cursor: 'default' }}>
                  <div>
                    <div className="co-name">{ind.replace(/-/g, ' ')}</div>
                  </div>
                  <span className="badge badge-approved" style={{ fontSize: 11 }}>Active</span>
                </div>
              </div>
            ))}
            {!meta.indications_active?.length && (
              <p style={{ fontSize: 13, color: '#888780' }}>No active indications listed</p>
            )}
          </div>
        </div>
      </div>

      {/* AI bar */}
      <AIBar company={slug} displayName={meta.full_name} />
    </div>
  )
}
