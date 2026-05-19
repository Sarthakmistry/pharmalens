// Strip [[wikilink]] syntax → plain text
function stripLinks(text) {
  return text.replace(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g, '$1').trim()
}

// Extract lines belonging to a named section (## or ### heading)
function sectionLines(body, heading) {
  const lines = body.split('\n')
  const start = lines.findIndex(l => /^#{1,4}\s/.test(l) && l.includes(heading))
  if (start === -1) return []

  const level = lines[start].match(/^(#{1,4})/)[1].length
  let end = lines.length
  for (let i = start + 1; i < lines.length; i++) {
    const m = lines[i].match(/^(#{1,4})\s/)
    if (m && m[1].length <= level) { end = i; break }
  }
  return lines.slice(start + 1, end)
}

// Parse a markdown table from an array of lines into [{header: value, ...}]
function parseTable(lines) {
  const tableLines = lines.filter(l => l.trim().startsWith('|'))
  if (tableLines.length < 2) return []

  const headers = tableLines[0].split('|').map(h => h.trim()).filter(Boolean)
  const rows = []
  for (let i = 2; i < tableLines.length; i++) {
    const cells = tableLines[i].split('|').map(c => c.trim()).filter(Boolean)
    if (!cells.length) continue
    const row = {}
    headers.forEach((h, j) => { row[h] = cells[j] ?? '' })
    rows.push(row)
  }
  return rows
}

// Parse "Drugs in class" table → [{drug, company, status, sentiment, ticker}]
export function parseDrugsTable(wikiBody) {
  const lines = sectionLines(wikiBody, 'Drugs in class')
  return parseTable(lines).map(r => ({
    drug:      stripLinks(r['Drug'] ?? ''),
    company:   stripLinks(r['Company'] ?? ''),
    status:    r['Status'] ?? '',
    sentiment: r['Sentiment'] ?? '',
    ticker:    stripLinks(r['Stock'] ?? r['Ticker'] ?? ''),
  })).filter(r => r.drug)
}

// Parse "Recent events" table → [{date, event, signal}]
export function parseEventsTable(wikiBody) {
  const lines = sectionLines(wikiBody, 'Recent events')
  return parseTable(lines).map(r => ({
    date:   r['Date'] ?? '',
    event:  stripLinks(r['Event'] ?? ''),
    signal: stripLinks(r['Signal'] ?? ''),
  })).filter(r => r.event)
}

// Map sentiment string → integer 1-5 for dot display
export function sentimentScore(s) {
  return { Bullish: 5, 'Moderately Bullish': 4, Neutral: 3, 'Moderately Bearish': 2, Bearish: 1 }[s] ?? 3
}

// Pick a colour for an event based on keywords in its text
export function eventColor(text) {
  const t = text.toLowerCase()
  if (t.includes('fda') || t.includes('approv') || t.includes('nda') || t.includes('bla')) return '#1D9E75'
  if (t.includes('earn') || t.includes('q1') || t.includes('q2') || t.includes('q3') || t.includes('q4') || t.includes('guidance')) return '#BA7517'
  if (t.includes('trial') || t.includes('nct') || t.includes('phase') || t.includes('enroll')) return '#378ADD'
  if (t.includes('tariff') || t.includes('risk') || t.includes('terminat') || t.includes('recall')) return '#E24B4A'
  return '#888780'
}
