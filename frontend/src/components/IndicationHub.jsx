import { useState, useEffect } from 'react'
import { fetchIndication } from '../api'
import { parseDrugsTable, parseEventsTable } from '../parseWiki'
import DrugCard from './DrugCard'
import EventList from './EventList'
import CompanyPanel from './CompanyPanel'
import AIBar from './AIBar'


export default function IndicationHub({ slug, stocks, companies, onSelectCompany }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    setData(null)
    fetchIndication(slug).then(d => { setData(d); setLoading(false) })
  }, [slug])

  if (loading) return <div className="loading">Loading {slug}…</div>
  if (!data) return null

  const { meta, wiki } = data
  const drugs = parseDrugsTable(wiki)
  const events = parseEventsTable(wiki)

  // Resolve companies active in this indication with their stock data
  const activeCompanies = (meta.companies_active ?? [])
    .map(coSlug => {
      const co = companies.find(c => c.slug === coSlug)
      if (!co) return null
      return { ...co, stock: stocks[co.ticker] }
    })
    .filter(Boolean)

  const displayName = meta.display_name ?? slug.replace(/-/g, ' ')

  return (
    <div>
      {/* Indication header */}
      <div className="ind-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <h1 className="ind-title">{displayName}</h1>
          {meta.last_updated && (
            <span className="ind-updated">wiki updated {meta.last_updated}</span>
          )}
        </div>
        <div className="ind-meta">
          {meta.drugs_approved?.length > 0 && (
            <span className="chip">{meta.drugs_approved.length} approved</span>
          )}
          {meta.drugs_pipeline?.length > 0 && (
            <span className="chip">{meta.drugs_pipeline.length} pipeline</span>
          )}
          {activeCompanies.length > 0 && (
            <span className="chip">{activeCompanies.length} companies</span>
          )}
          {meta.active_trials > 0 && (
            <span className="chip">{meta.active_trials} active trials</span>
          )}
        </div>
      </div>

      {/* Drug cards */}
      {drugs.length > 0 && (
        <>
          <p className="sec-label">Drugs in class</p>
          <div className="drug-grid">
            {drugs.map((d, i) => {
              const co = companies.find(c => c.slug === d.company)
              const drug = co ? { ...d, company: co.full_name } : d
              return <DrugCard key={i} drug={drug} stock={stocks[d.ticker]} />
            })}
          </div>
        </>
      )}

      {/* Events + Companies */}
      <div className="bottom-grid">
        <EventList events={events} />
        <CompanyPanel companies={activeCompanies} onSelectCompany={onSelectCompany} />
      </div>

      {/* Embedded AI bar */}
      <AIBar indication={slug} displayName={displayName} />
    </div>
  )
}
