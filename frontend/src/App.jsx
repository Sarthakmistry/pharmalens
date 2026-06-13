import { useState, useEffect } from 'react'
import { fetchIndications, fetchCompanies, fetchStocks } from './api'
import TickerBar from './components/TickerBar'
import Sidebar from './components/Sidebar'
import IndicationHub from './components/IndicationHub'
import CompanyView from './components/CompanyView'
import AIBar from './components/AIBar'

export default function App() {
  const [indications, setIndications] = useState([])
  const [companies, setCompanies] = useState([])
  const [stocks, setStocks] = useState({}) // keyed by ticker
  const [activeIndication, setActiveIndication] = useState(null)
  const [activeCompany, setActiveCompany] = useState(null)

  const aiDisplayName = activeCompany
    ? companies.find(c => c.slug === activeCompany)?.full_name ?? activeCompany
    : activeIndication
      ? indications.find(i => i.slug === activeIndication)?.display_name ?? activeIndication
      : null

  const loadStocks = () =>
    fetchStocks().then(data => {
      const byTicker = {}
      data.forEach(s => { byTicker[s.ticker] = s })
      setStocks(byTicker)
    })

  useEffect(() => {
    fetchIndications().then(data => {
      setIndications(data)
      if (data.length) setActiveIndication(data[0].slug)
    })
    fetchCompanies().then(setCompanies)
    loadStocks()

    // Refresh stock prices every 60 s
    const interval = setInterval(loadStocks, 60_000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="app-wrapper">
      <TickerBar stocks={Object.values(stocks)} />
      <div className="app">
        <Sidebar
          indications={indications}
          companies={companies}
          activeIndication={activeIndication}
          activeCompany={activeCompany}
          onSelectIndication={slug => { setActiveIndication(slug); setActiveCompany(null) }}
          onSelectCompany={slug => { setActiveCompany(slug); setActiveIndication(null) }}
        />
        <main className="main">
          {activeIndication && (
            <IndicationHub
              key={activeIndication}
              slug={activeIndication}
              stocks={stocks}
              companies={companies}
              onSelectCompany={slug => { setActiveCompany(slug); setActiveIndication(null) }}
            />
          )}
          {activeCompany && (
            <CompanyView
              key={activeCompany}
              slug={activeCompany}
              stocks={stocks}
              onSelectIndication={slug => { setActiveIndication(slug); setActiveCompany(null) }}
            />
          )}
        </main>
        <AIBar
          indication={activeIndication}
          company={activeCompany}
          displayName={aiDisplayName}
        />
      </div>
    </div>
  )
}
