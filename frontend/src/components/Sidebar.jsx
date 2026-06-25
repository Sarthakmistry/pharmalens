import { useState } from 'react'

export default function Sidebar({
  indications,
  companies,
  news,
  activeIndication,
  activeCompany,
  activeArticle,
  onSelectIndication,
  onSelectCompany,
  onSelectArticle,
}) {
  const [search, setSearch] = useState('')

  const q = search.toLowerCase()
  const filteredIndications = indications.filter(i =>
    i.display_name.toLowerCase().includes(q) || i.slug.includes(q)
  )
  const filteredCompanies = companies
    .filter(c => c.full_name.toLowerCase().includes(q) || c.slug.includes(q))
    .sort((a, b) => a.full_name.localeCompare(b.full_name))

  return (
    <aside className="sidebar">
      <div className="logo">
        Pharma<span className="logo-accent">Lens</span>
      </div>

      <div className="sidebar-search">
        <input
          type="text"
          placeholder="Search drug, company…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      <div className="nav-label">Companies</div>
      {filteredCompanies.map(co => (
        <div
          key={co.slug}
          className={`nav-item ${activeCompany === co.slug ? 'active' : ''}`}
          onClick={() => onSelectCompany(co.slug)}
        >
          {co.full_name}
        </div>
      ))}

      {filteredIndications.length > 0 && (
        <div className="nav-section">
          <div className="nav-label">Indications</div>
          {filteredIndications.map(ind => (
            <div
              key={ind.slug}
              className={`nav-item ${activeIndication === ind.slug ? 'active' : ''}`}
              onClick={() => onSelectIndication(ind.slug)}
            >
              <span className="nav-dot" />
              {ind.display_name}
            </div>
          ))}
        </div>
      )}

      {news?.length > 0 && (
        <div className="nav-section">
          <div className="nav-label">News</div>
          {news.slice(0, 12).map(article => (
            <div
              key={article.url}
              className={`nav-item ${activeArticle === article.url ? 'active' : ''}`}
              onClick={() => onSelectArticle(article.url)}
              title={article.title}
            >
              {article.title}
            </div>
          ))}
        </div>
      )}
    </aside>
  )
}
