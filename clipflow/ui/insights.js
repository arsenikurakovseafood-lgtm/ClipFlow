const ledgerForm = document.getElementById('ledger-form')
const insightsStatus = document.getElementById('insights-status')
const formatEUR = new Intl.NumberFormat('en', {style: 'currency', currency: 'EUR'})
const euros = cents => formatEUR.format(cents / 100)
let insightsSignature = ''
let transactionKey

function statistic(label, value) {
  const item = element('div')
  item.append(element('strong', value), element('span', label))
  return item
}

function insightList(container, nodes, empty) {
  document.getElementById(container).replaceChildren(...(nodes.length ? nodes : [element('p', empty)]))
}

async function ledgerRequest(url, data = {}) {
  try {
    const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)})
    if (!response.ok) throw new Error((await response.json()).error)
    insightsStatus.textContent = 'Transaction saved.'
    await refreshInsights()
    return true
  } catch (error) {
    insightsStatus.textContent = error.message
    return false
  }
}

function transactionCard(entry) {
  const row = element('article')
  row.className = 'campaign-card'
  row.append(element('h3', euros(entry.cents) + ' · ' + entry.kind.replaceAll('_', ' ')),
    element('p', entry.note), element('small', 'Owner-reported · ' + entry.state))
  if (entry.state === 'pending') {
    const controls = element('div')
    controls.className = 'campaign-actions'
    controls.append(action('Confirm cash transaction', () => ledgerRequest('/api/ledger/' + entry.id + '/confirm')))
    row.append(controls)
  }
  return row
}

function metricCard(metric) {
  const row = element('article')
  row.className = 'campaign-card'
  const counts = ['views', 'likes', 'comments', 'shares', 'saves', 'clicks', 'conversions']
    .filter(key => typeof metric[key] === 'number').map(key => `${metric[key].toLocaleString()} ${key}`)
  const source = metric.observed_at ? 'YouTube Data API · ' + new Date(metric.observed_at).toLocaleString()
    : `${providers[metric.channel]} · owner-reported ${metric.hours}h · ${metric.creative}`
  row.append(element('h3', metric.clip), element('p', `${metric.campaign} · ${source}`),
    element('small', counts.join(' · ')))
  return row
}

async function refreshInsights() {
  try {
    const response = await fetch('/api/insights')
    if (!response.ok) throw new Error()
    const data = await response.json()
    const signature = JSON.stringify(data)
    if (signature === insightsSignature) return
    insightsSignature = signature
    const {confirmed, pending, estimated} = data.totals
    const cash = confirmed.income - confirmed.expense
    document.getElementById('overview-cash').textContent = euros(cash)
    document.getElementById('revenue-totals').replaceChildren(
      statistic('Confirmed income', euros(confirmed.income)), statistic('Confirmed expenses', euros(confirmed.expense)),
      statistic('Confirmed cash result', euros(cash)), statistic('Pending income', euros(pending.income)),
      statistic('Pending expenses', euros(pending.expense)), statistic('Estimated expenses', euros(estimated.expense)))
    document.getElementById('workspace-usage').replaceChildren(
      statistic('Recorded render time', Math.round(data.usage.render_seconds) + ' s'),
      statistic('Storage reserved', Math.ceil(data.usage.storage_reserved_bytes / 1048576) + ' MiB'),
      statistic('Transcription budget reserved', '$' + (data.usage.transcription_reserved_micro_usd / 1000000).toFixed(4)))
    insightList('ledger-entries', data.entries.map(transactionCard), 'No transactions recorded.')
    insightList('performance-list', [...data.metrics, ...data.youtube].map(metricCard), 'Record a published post in Campaigns to add its measurements.')
    const percent = new Intl.NumberFormat('en', {style: 'percent', maximumFractionDigits: 2})
    insightList('overview-decisions', data.decisions.map(decision => element('p',
      `${decision.campaign} · ${decision.hours}h: test another ${decision.candidate} hook. ` +
      `${decision.count} clips averaged ${percent.format(decision.rate)} ${decision.measure} per view, ` +
      `versus ${percent.format(decision.comparison_rate)} for ${decision.comparison}.`)),
    'Add comparable checkpoints for two hook formats. Suggestions need at least three clips and 300 views per format.')
  } catch {
    insightsStatus.textContent = 'Could not load workspace measurements.'
  }
}

ledgerForm.addEventListener('input', () => { transactionKey = undefined })
ledgerForm.addEventListener('submit', async event => {
  event.preventDefault()
  const values = Object.fromEntries(new FormData(ledgerForm))
  const button = ledgerForm.querySelector('button')
  transactionKey ||= crypto.randomUUID()
  button.disabled = true
  try {
    if (await ledgerRequest('/api/ledger', {key: transactionKey, kind: values.kind, state: values.state,
      campaign_id: values.campaign || null, cents: Math.round(Number(values.amount) * 100), note: values.note})) {
      ledgerForm.reset()
      transactionKey = undefined
    }
  } finally { button.disabled = false }
})
refreshInsights()

async function refreshSettings(paused) {
  const status = document.getElementById('settings-status')
  try {
    const response = await fetch('/api/settings', paused === undefined ? {} : {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({paused})})
    if (!response.ok) throw new Error('Could not load or change processing settings.')
    const data = await response.json()
    status.textContent = data.paused ? 'Workspace processing is paused.' : 'Workspace processing is active.'
    document.getElementById('settings-controls').replaceChildren(action(data.paused ? 'Resume processing' : 'Pause processing',
      () => refreshSettings(!data.paused)))
    insightList('workspace-audit', data.events.map(event => element('p',
      `${event.event.replaceAll('_', ' ')} · ${new Date(event.created_at).toLocaleString()}`)), 'No decisions recorded.')
  } catch (error) { status.textContent = error.message }
}

if (location.hash === '#settings') refreshSettings()
window.addEventListener('hashchange', () => {
  if (['#revenue', '#overview', '#settings', ''].includes(location.hash)) refreshInsights()
  if (location.hash === '#settings') refreshSettings()
})
