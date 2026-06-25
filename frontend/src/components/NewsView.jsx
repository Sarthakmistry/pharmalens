import { useState, useEffect } from 'react'
import { fetchArticle } from '../api'

export default function NewsView({ url }) {
  const [article, setArticle] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    setArticle(null)
    fetchArticle(url).then(d => { setArticle(d); setLoading(false) })
  }, [url])

  if (loading) return <div className="loading">Loading article…</div>
  if (!article) return null

  const dateLabel = article.published_date ? article.published_date.slice(0, 10) : ''

  return (
    <div>
      <div className="ind-header">
        <h1 className="ind-title">{article.title}</h1>
        <div className="ind-meta">
          {dateLabel && <span className="chip">{dateLabel}</span>}
          <span className="chip">BioSpace</span>
        </div>
      </div>

      <div className="card">
        {article.body_text.split('\n\n').map((para, i) => (
          <p key={i} className="evt-text" style={{ marginBottom: 12 }}>{para}</p>
        ))}
        <a href={article.url} target="_blank" rel="noopener noreferrer" className="co-name" style={{ display: 'inline-block', marginTop: 4 }}>
          Read on BioSpace ↗
        </a>
      </div>
    </div>
  )
}
