import { useState, useRef } from 'react'
import { streamAsk } from '../api'

const SparkIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="8" r="6.5" stroke="#888780" strokeWidth="1.2" />
    <path d="M6 8h4M8 6v4" stroke="#888780" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
)

// Derive a readable label for a tool call
function toolLabel(name, input) {
  if (name === 'read_wiki_page') return `Reading ${input.page_path ?? '…'}`
  if (name === 'list_wiki_pages') return `Listing ${input.prefix || 'wiki'}…`
  if (name === 'get_stock_price') return `Fetching ${input.ticker}…`
  if (name === 'search_wiki') return `Searching wiki for "${input.query}"…`
  return name
}

export default function AIBar({ indication, company, displayName }) {
  const [question, setQuestion] = useState('')
  const [toolCalls, setToolCalls] = useState([])  // [{name, input, done}]
  const [answer, setAnswer] = useState('')
  const [streaming, setStreaming] = useState(false)
  const inputRef = useRef(null)

  const submit = async q => {
    if (!q.trim() || streaming) return
    setStreaming(true)
    setToolCalls([])
    setAnswer('')
    setQuestion('')

    try {
      for await (const event of streamAsk(q, indication ?? null, company ?? null)) {
        if (event.type === 'tool_call') {
          setToolCalls(prev => [...prev, { name: event.name, input: event.input, done: false }])
        } else if (event.type === 'tool_result') {
          setToolCalls(prev =>
            prev.map((t, i) => i === prev.length - 1 ? { ...t, done: true } : t)
          )
        } else if (event.type === 'text') {
          setAnswer(prev => prev + event.content)
        } else if (event.type === 'done') {
          setStreaming(false)
        }
      }
    } catch (err) {
      setAnswer(`Error: ${err.message}`)
      setStreaming(false)
    }
  }

  const suggestions = [
    `Tariff impact on this class?`,
    `Clinical comparison of key drugs?`,
    `Upcoming trial readouts?`,
    `Key pipeline risks?`,
  ]

  const hasResponse = toolCalls.length > 0 || answer || (streaming && !answer)

  return (
    <div className="ai-section">
      {/* Response panel — shown once agent starts */}
      {hasResponse && (
        <div className="ai-response">
          {toolCalls.length > 0 && (
            <div className="tool-chips">
              {toolCalls.map((t, i) => (
                <span key={i} className={`tool-chip ${t.done ? 'done' : ''}`}>
                  {t.done ? '✓' : '⟳'} {toolLabel(t.name, t.input)}
                </span>
              ))}
            </div>
          )}
          {streaming && !answer && (
            <div className="ai-thinking">Thinking…</div>
          )}
          {answer && <div className="ai-text">{answer}</div>}
        </div>
      )}

      {/* Input bar */}
      <div className="ai-bar" onClick={() => inputRef.current?.focus()}>
        <SparkIcon />
        <input
          ref={inputRef}
          className="ai-input"
          type="text"
          placeholder={`Ask about ${displayName ?? 'this indication'}…`}
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit(question)}
          disabled={streaming}
        />
        {streaming
          ? <span className="ai-spinner" />
          : <span className="ai-hint">↵</span>
        }
      </div>

      {/* Suggestion chips */}
      <div className="chip-row">
        {suggestions.map((s, i) => (
          <span key={i} className="q-chip" onClick={() => submit(s)}>
            {s}
          </span>
        ))}
      </div>
    </div>
  )
}
