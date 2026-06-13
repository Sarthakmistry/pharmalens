import { useEffect, useRef, useState, useCallback } from 'react'
import * as d3 from 'd3'
import { fetchStockHistory } from '../api'

const PERIODS  = ['1d', '5d', '1mo', '1y']
const PERIOD_LABELS = { '1d': '1D', '5d': '5D', '1mo': '1M', '1y': '1Y' }
const MARGIN   = { top: 12, right: 12, bottom: 28, left: 52 }

function computeMA(candles, window) {
  return candles.map((d, i) => {
    if (i < window - 1) return null
    const slice = candles.slice(i - window + 1, i + 1)
    return slice.reduce((s, x) => s + x.c, 0) / window
  })
}

export default function StockChart({ slug }) {
  const [period, setPeriod]   = useState('1d')
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const svgRef  = useRef(null)
  const wrapRef = useRef(null)

  useEffect(() => {
    setLoading(true)
    setData(null)
    fetchStockHistory(slug, period).then(d => { setData(d); setLoading(false) })
  }, [slug, period])

  const draw = useCallback(() => {
    if (!data?.candles?.length || !svgRef.current || !wrapRef.current) return

    const W = wrapRef.current.clientWidth
    const H = 200
    const iW = W - MARGIN.left - MARGIN.right
    const iH = H - MARGIN.top  - MARGIN.bottom

    const candles    = data.candles.map(d => ({ ...d, t: new Date(d.t) }))
    const prevClose  = data.prev_close ?? candles[0]?.o ?? candles[0]?.c
    const lastPrice  = candles[candles.length - 1]?.c ?? prevClose
    const isUp       = lastPrice >= prevClose
    const lineColor  = isUp ? '#1D9E75' : '#E24B4A'
    const areaColor  = isUp ? '#1D9E75' : '#E24B4A'

    const xScale = d3.scaleTime()
      .domain(d3.extent(candles, d => d.t))
      .range([0, iW])

    const yMin = d3.min(candles, d => d.l) * 0.999
    const yMax = d3.max(candles, d => d.h) * 1.001
    const yScale = d3.scaleLinear().domain([yMin, yMax]).range([iH, 0])

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    svg.attr('width', W).attr('height', H)

    const g = svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

    // Gradient
    const gradId = `grad-${slug}-${period}`
    const defs   = svg.append('defs')
    const grad   = defs.append('linearGradient').attr('id', gradId).attr('x1','0').attr('y1','0').attr('x2','0').attr('y2','1')
    grad.append('stop').attr('offset','0%').attr('stop-color', areaColor).attr('stop-opacity', 0.18)
    grad.append('stop').attr('offset','100%').attr('stop-color', areaColor).attr('stop-opacity', 0)

    // Area
    const area = d3.area()
      .x(d => xScale(d.t))
      .y0(iH)
      .y1(d => yScale(d.c))
      .curve(d3.curveMonotoneX)

    g.append('path')
      .datum(candles)
      .attr('fill', `url(#${gradId})`)
      .attr('d', area)

    // Price line
    const line = d3.line()
      .x(d => xScale(d.t))
      .y(d => yScale(d.c))
      .curve(d3.curveMonotoneX)

    g.append('path')
      .datum(candles)
      .attr('fill', 'none')
      .attr('stroke', lineColor)
      .attr('stroke-width', 1.5)
      .attr('d', line)

    // Moving averages (only for 1mo and 1y)
    if (period === '1mo' || period === '1y') {
      const maConfigs = period === '1y'
        ? [{ w: 50, color: '#BA7517' }, { w: 200, color: '#185FA5' }]
        : [{ w: 20, color: '#BA7517' }]

      maConfigs.forEach(({ w, color }) => {
        const maVals = computeMA(candles, w)
        const maPairs = candles.map((d, i) => maVals[i] != null ? { t: d.t, v: maVals[i] } : null).filter(Boolean)
        if (!maPairs.length) return

        const maLine = d3.line().x(d => xScale(d.t)).y(d => yScale(d.v)).curve(d3.curveMonotoneX)
        g.append('path')
          .datum(maPairs)
          .attr('fill', 'none')
          .attr('stroke', color)
          .attr('stroke-width', 1)
          .attr('stroke-dasharray', '3 2')
          .attr('d', maLine)
      })
    }

    // Prev-close reference line (1D only)
    if (period === '1d' && prevClose) {
      const y = yScale(prevClose)
      g.append('line')
        .attr('x1', 0).attr('y1', y).attr('x2', iW).attr('y2', y)
        .attr('stroke', '#ccc').attr('stroke-width', 1).attr('stroke-dasharray', '4 3')
    }

    // X axis
    const xTicks = period === '1d' ? 4 : period === '5d' ? 5 : period === '1mo' ? 4 : 6
    g.append('g')
      .attr('transform', `translate(0,${iH})`)
      .call(
        d3.axisBottom(xScale).ticks(xTicks)
          .tickFormat(d => period === '1d'
            ? d3.timeFormat('%-I%p')(d).toLowerCase()
            : period === '1y' ? d3.timeFormat('%b %y')(d)
            : d3.timeFormat('%b %d')(d)
          )
          .tickSize(3)
      )
      .call(ax => ax.select('.domain').remove())
      .call(ax => ax.selectAll('text').attr('font-size', 10).attr('fill', '#888'))
      .call(ax => ax.selectAll('.tick line').attr('stroke', '#ddd'))

    // Y axis
    g.append('g')
      .call(d3.axisLeft(yScale).ticks(4).tickFormat(d => `$${d3.format(',.0f')(d)}`).tickSize(3))
      .call(ax => ax.select('.domain').remove())
      .call(ax => ax.selectAll('text').attr('font-size', 10).attr('fill', '#888'))
      .call(ax => ax.selectAll('.tick line').attr('stroke', '#ddd'))

    // Crosshair + tooltip
    const tooltip = g.append('g').attr('display', 'none')
    tooltip.append('line')
      .attr('class', 'xhair')
      .attr('y1', 0).attr('y2', iH)
      .attr('stroke', '#aaa').attr('stroke-width', 1).attr('stroke-dasharray', '3 2')
    const dot = tooltip.append('circle').attr('r', 3).attr('fill', lineColor).attr('stroke', '#fff').attr('stroke-width', 1.5)
    const box = tooltip.append('g')
    const rect = box.append('rect').attr('fill', '#1a1a18').attr('rx', 4).attr('height', 28).attr('y', -34)
    const txt  = box.append('text').attr('fill', '#fff').attr('font-size', 11).attr('y', -16).attr('text-anchor', 'middle')

    const bisect = d3.bisector(d => d.t).left
    svg.append('rect')
      .attr('width', iW).attr('height', iH)
      .attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)
      .attr('fill', 'none').attr('pointer-events', 'all')
      .on('mousemove', function(event) {
        const [mx] = d3.pointer(event, this)
        const x0   = xScale.invert(mx)
        const i    = Math.min(bisect(candles, x0), candles.length - 1)
        const d    = candles[i]
        const cx   = xScale(d.t)
        const cy   = yScale(d.c)

        tooltip.attr('display', null)
        tooltip.select('.xhair').attr('x1', cx).attr('x2', cx)
        dot.attr('cx', cx).attr('cy', cy)

        const label  = `$${d.c.toFixed(2)}`
        txt.text(label)
        const tw = label.length * 6.5 + 12
        rect.attr('width', tw).attr('x', -tw / 2)
        box.attr('transform', `translate(${cx},${cy})`)
      })
      .on('mouseleave', () => tooltip.attr('display', 'none'))

  }, [data, period, slug])

  useEffect(() => {
    draw()
    const ro = new ResizeObserver(draw)
    if (wrapRef.current) ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [draw])

  return (
    <div ref={wrapRef} style={{ width: '100%' }}>
      {/* Period tabs */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 8 }}>
        {PERIODS.map(p => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            style={{
              padding: '3px 10px',
              fontSize: 12,
              fontWeight: period === p ? 600 : 400,
              background: period === p ? '#1a1a18' : 'transparent',
              color: period === p ? '#fff' : '#888',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            {PERIOD_LABELS[p]}
          </button>
        ))}
        {(period === '1mo' || period === '1y') && (
          <div style={{ display: 'flex', gap: 10, marginLeft: 12, alignItems: 'center', fontSize: 10, color: '#888' }}>
            <span><span style={{ display: 'inline-block', width: 18, borderTop: '1px dashed #BA7517', verticalAlign: 'middle', marginRight: 4 }} />
              {period === '1y' ? '50d MA' : '20d MA'}
            </span>
            {period === '1y' && (
              <span><span style={{ display: 'inline-block', width: 18, borderTop: '1px dashed #185FA5', verticalAlign: 'middle', marginRight: 4 }} />200d MA</span>
            )}
          </div>
        )}
      </div>

      {/* Chart */}
      {loading
        ? <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, color: '#888' }}>Loading…</div>
        : <svg ref={svgRef} style={{ display: 'block' }} />
      }
    </div>
  )
}
