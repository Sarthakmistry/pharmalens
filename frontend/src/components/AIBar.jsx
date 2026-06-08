import { useState, useRef, useEffect } from 'react'
import { streamAsk } from '../api'

const SparkIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="8" r="6.5" stroke="#888780" strokeWidth="1.2" />
    <path d="M6 8h4M8 6v4" stroke="#888780" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
)

function toolLabel(name, input) {
  if (name === 'read_wiki_page') return `Reading ${input.page_path ?? '…'}`
  if (name === 'list_wiki_pages') return `Listing ${input.prefix || 'wiki'}…`
  if (name === 'get_stock_price') return `Fetching ${input.ticker}…`
  if (name === 'search_wiki') return `Searching wiki for "${input.query}"…`
  return name
}

export default function AIBar({ indication, company, displayName }) {
  const [question, setQuestion] = useState('')
  // history = [{question, toolCalls: [{name, input, done}], answer, streaming}]
  const [history, setHistory] = useState([])
  const [streaming, setStreaming] = useState(false)
  const inputRef = useRef(null)
  const bottomRef = useRef(null)

  // Scroll to bottom whenever history updates
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history])

  const updateLast = (updater) =>
    setHistory(prev => {
      const next = [...prev]
      next[next.length - 1] = updater(next[next.length - 1])
      return next
    })

  const submit = async q => {
    if (!q.trim() || streaming) return
    setStreaming(true)
    setQuestion('')

    // Append new entry — keep all previous entries intact
    setHistory(prev => [...prev, { question: q, toolCalls: [], answer: '', streaming: true }])

    try {
      for await (const event of streamAsk(q, indication ?? null, company ?? null)) {
        if (event.type === 'tool_call') {
          updateLast(entry => ({
            ...entry,
            toolCalls: [...entry.toolCalls, { name: event.name, input: event.input, done: false }],
          }))
        } else if (event.type === 'tool_result') {
          updateLast(entry => {
            const toolCalls = entry.toolCalls.map((t, i) =>
              i === entry.toolCalls.length - 1 ? { ...t, done: true } : t
            )
            return { ...entry, toolCalls }
          })
        } else if (event.type === 'text') {
          updateLast(entry => ({ ...entry, answer: entry.answer + event.content }))
        } else if (event.type === 'done') {
          updateLast(entry => ({ ...entry, streaming: false }))
          setStreaming(false)
        }
      }
    } catch (err) {
      updateLast(entry => ({ ...entry, answer: `Error: ${err.message}`, streaming: false }))
      setStreaming(false)
    }
  }

  const suggestions = [
    `Tariff impact on this class?`,
    `Clinical comparison of key drugs?`,
    `Upcoming trial readouts?`,
    `Key pipeline risks?`,
  ]

  return (
    <div className="ai-section">
      {/* Conversation history */}
      {history.length > 0 && (
        <div className="ai-history">
          {history.map((entry, i) => (
            <div key={i} className="ai-exchange">
              {/* Question bubble */}
              <div className="ai-question">{entry.question}</div>

              {/* Response */}
              <div className="ai-response">
                {entry.toolCalls.length > 0 && (
                  <div className="tool-chips">
                    {entry.toolCalls.map((t, j) => (
                      <span key={j} className={`tool-chip ${t.done ? 'done' : ''}`}>
                        {t.done ? '✓' : '⟳'} {toolLabel(t.name, t.input)}
                      </span>
                    ))}
                  </div>
                )}
                {entry.streaming && !entry.answer && (
                  <div className="ai-thinking">Thinking…</div>
                )}
                {entry.answer && <div className="ai-text">{entry.answer}</div>}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
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
