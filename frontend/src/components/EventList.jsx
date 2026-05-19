import { eventColor } from '../parseWiki'

export default function EventList({ events }) {
  return (
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
  )
}
