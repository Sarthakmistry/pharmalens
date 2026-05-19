export default function TickerBar({ stocks }) {
  if (!stocks.length) return <div className="ticker-bar" style={{ height: 33 }} />

  // Double the list so the CSS animation loops seamlessly
  const items = [...stocks, ...stocks]

  return (
    <div className="ticker-bar">
      <div className="ticker-track">
        {items.map((s, i) => {
          const dir = s.change_pct > 0 ? 'pos' : s.change_pct < 0 ? 'neg' : 'neu'
          return (
            <span key={i} className="ticker-item">
              <span className="ticker-sym">{s.ticker}</span>
              {s.price != null && (
                <span className="ticker-price">${s.price.toFixed(2)}</span>
              )}
              {s.change_pct != null && (
                <span className={`ticker-change ${dir}`}>
                  {s.change_pct > 0 ? '+' : ''}{s.change_pct.toFixed(2)}%
                </span>
              )}
            </span>
          )
        })}
      </div>
    </div>
  )
}
