import { sentimentScore } from '../parseWiki'

function statusClass(status) {
  const s = status.toLowerCase()
  if (s.includes('approved')) return 'badge-approved'
  if (s.includes('phase 3') || s.includes('ph3')) return 'badge-ph3'
  if (s.includes('phase 2') || s.includes('ph2')) return 'badge-ph2'
  if (s.includes('pipeline') || s.includes('phase')) return 'badge-pipeline'
  return ''
}

export default function DrugCard({ drug, stock }) {
  const score = sentimentScore(drug.sentiment)
  const changePct = stock?.change_pct

  const priceClass =
    changePct > 0 ? 'price-pos' : changePct < 0 ? 'price-neg' : 'price-neu'
  const priceLabel =
    changePct != null
      ? `${drug.ticker} ${changePct > 0 ? '+' : ''}${changePct.toFixed(2)}%`
      : drug.ticker || ''

  return (
    <div className="drug-card">
      <div className="drug-name">{drug.drug}</div>
      <div className="drug-co">{drug.company}</div>
      <span className={`badge ${statusClass(drug.status)}`}>{drug.status}</span>

      <hr className="divider" />

      <div className="sent-label">Mgmt. sentiment</div>
      <div className="dots">
        {[1, 2, 3, 4, 5].map(i => (
          <span key={i} className={`dot ${i <= score ? 'dot-filled' : 'dot-empty'}`} />
        ))}
      </div>

      {priceLabel && <span className={priceClass}>{priceLabel}</span>}
    </div>
  )
}
