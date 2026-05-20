export default function CompanyPanel({ companies, onSelectCompany }) {
  return (
    <div className="card">
      <p className="sec-label" style={{ marginBottom: 12 }}>Companies in class</p>
      <div className="co-list">
        {companies.map((co, i) => {
          const changePct = co.stock?.change_pct
          const priceClass =
            changePct > 0 ? 'price-pos' : changePct < 0 ? 'price-neg' : 'price-neu'
          const label =
            changePct != null
              ? `${changePct > 0 ? '+' : ''}${changePct.toFixed(2)}%`
              : '—'

          return (
            <div key={co.slug}>
              {i > 0 && <hr className="divider" style={{ margin: 0 }} />}
              <div className="co-row" style={{ cursor: onSelectCompany ? 'pointer' : 'default' }} onClick={() => onSelectCompany?.(co.slug)}>
                <div>
                  <div className="co-name">{co.full_name}</div>
                  <div className="co-sub">
                    {co.drugs?.slice(0, 3).join(', ')}
                    {co.drugs?.length > 3 ? ` +${co.drugs.length - 3}` : ''}
                  </div>
                </div>
                <span className={priceClass}>{label}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
