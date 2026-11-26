const campaignForm = document.getElementById('campaign-form')
const campaignStatus = document.getElementById('campaign-status')
const providers = {youtube: 'YouTube Shorts', instagram: 'Instagram Reels', tiktok: 'TikTok'}
let campaignSignature = ''

async function campaignAction(path, data = {}) {
  try {
    const response = await fetch(path, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error || 'Request failed')
    campaignStatus.textContent = 'Saved.'
    await refreshCampaigns()
    return true
  } catch (error) {
    campaignStatus.textContent = error.message
    return false
  }
}

function element(tag, text) {
  const node = document.createElement(tag)
  if (text !== undefined) node.textContent = text
  return node
}

function action(label, callback) {
  const button = element('button', label)
  button.type = 'button'
  button.addEventListener('click', async () => {
    button.disabled = true
    try { await callback() } finally { button.disabled = false }
  })
  return button
}

function scheduleForm(base, ready) {
  if (!ready.length) return element('small', 'Render a clip before scheduling it.')
  const form = element('form')
  const clip = element('select')
  clip.setAttribute('aria-label', 'Ready clip')
  for (const job of ready) {
    const option = element('option', job.name)
    option.value = job.id
    clip.append(option)
  }
  const time = element('input')
  time.type = 'datetime-local'
  time.required = true
  time.setAttribute('aria-label', 'Manual publishing time')
  const submit = element('button', 'Schedule manual handoff')
  form.append(clip, time, submit)
  form.addEventListener('submit', async event => {
    event.preventDefault()
    submit.disabled = true
    try {
      if (await campaignAction(base + '/schedule', {
        job_id: clip.value, scheduled_at: new Date(time.value).toISOString()
      })) form.reset()
    } finally { submit.disabled = false }
  })
  return form
}

function batchScheduleForm(base, batches) {
  const form = element('form')
  const selection = element('select')
  selection.setAttribute('aria-label', 'Finished batch')
  for (const batch of batches) {
    const option = element('option', batch.name)
    option.value = batch.id
    selection.append(option)
  }
  const date = element('input')
  date.type = 'datetime-local'
  date.required = true
  date.setAttribute('aria-label', 'First batch release')
  const submit = element('button', 'Schedule entire batch')
  form.append(selection, date, submit)
  form.addEventListener('submit', async event => {
    event.preventDefault()
    submit.disabled = true
    try {
      const scheduled = await campaignAction(base + '/schedule-batch', {
        batch_id: selection.value, scheduled_at: new Date(date.value).toISOString()
      })
      if (scheduled) form.reset()
    } finally { submit.disabled = false }
  })
  return form
}

function campaignCard(campaign, ready, batches) {
  const base = '/api/campaigns/' + campaign.id
  const card = element('article')
  card.className = 'campaign-card'
  const euros = new Intl.NumberFormat('en', {style: 'currency', currency: 'EUR'})
  card.append(element('h3', campaign.name), element('p', campaign.goal),
    element('small', [campaign.state.toUpperCase(), providers[campaign.channel],
      campaign.planned_posts + ' planned, every ' + campaign.cadence_days + ' days',
      campaign.duration_days + ' days total', euros.format(campaign.budget_cents / 100) + ' budget target'
    ].join(' · ')))
  const controls = element('div')
  controls.className = 'campaign-actions'
  const states = {draft: ['approve', 'stop'], active: ['pause', 'stop'], paused: ['resume', 'stop']}
  for (const next of states[campaign.state] || []) {
    controls.append(action(next[0].toUpperCase() + next.slice(1), () => campaignAction(base + '/' + next)))
  }
  card.append(controls)
  if (campaign.state === 'active') {
    card.append(scheduleForm(base, ready))
    if (batches.length) card.append(batchScheduleForm(base, batches))
  }
  return card
}

function postCard(post) {
  const card = element('article')
  card.className = 'campaign-card'
  const link = element('a', 'Open clip')
  link.href = '/media/' + post.job_id
  card.append(element('h3', post.name), element('p', post.campaign_name + ' · ' + providers[post.channel]),
    element('p', new Date(post.scheduled_at).toLocaleString() + ' · ' + post.state.replaceAll('_', ' ')))
  if (!['asset_expired', 'cancelled'].includes(post.state)) card.append(link)
  if (post.state === 'due') card.append(action('Mark handed off', () => campaignAction('/api/manual-posts/' + post.id + '/handoff')))
  return card
}

async function refreshCampaigns() {
  try {
    const paths = ['/api/campaigns', '/api/jobs']
    const responses = await Promise.all(paths.map(path => fetch(path)))
    if (responses.some(response => !response.ok)) throw new Error()
    const [data, jobs] = await Promise.all(responses.map(response => response.json()))
    const ready = jobs.filter(job => job.state === 'ready')
    const batches = jobs.filter(job => {
      if (job.state !== 'prepared') return false
      const clips = jobs.filter(clip => clip.batch_parent === job.id)
      return clips.length && clips.every(clip => clip.state === 'ready')
    })
    const signature = JSON.stringify([data, ready.map(job => job.id), batches.map(job => job.id)])
    if (signature === campaignSignature) return
    campaignSignature = signature
    document.getElementById('campaign-list').replaceChildren(...(data.campaigns.length
      ? data.campaigns.map(campaign => campaignCard(campaign, ready, batches))
      : [element('p', 'No plans yet. Start with your content goal.')]))
    document.getElementById('publication-list').replaceChildren(...(data.posts.length
      ? data.posts.map(postCard)
      : [element('p', 'Scheduled, approved campaign clips will appear here.')]))
  } catch {
    campaignStatus.textContent = 'Could not refresh campaigns.'
  }
}

campaignForm.addEventListener('submit', async event => {
  event.preventDefault()
  const values = Object.fromEntries(new FormData(campaignForm))
  const submit = campaignForm.querySelector('button')
  submit.disabled = true
  try {
    if (await campaignAction('/api/campaigns', {
      name: values.name, goal: values.goal, channel: values.channel,
      duration_days: Number(values.duration_days), cadence_days: Number(values.cadence_days),
      budget_cents: Math.round(Number(values.budget) * 100)
    })) campaignForm.reset()
  } finally { submit.disabled = false }
})
refreshCampaigns()
setInterval(refreshCampaigns, 3000)


const agent = document.getElementById('agent-form')
const agentStatus = document.getElementById('agent-status')
const agentPlan = document.getElementById('agent-plan')
let agentSignature = ''

async function refreshAgent() {
  if (agent.hidden) return
  try {
    const response = await fetch('/api/plans')
    if (!response.ok) throw new Error('Could not load AI plans.')
    const [plan] = await response.json()
    const signature = JSON.stringify(plan || null)
    if (signature === agentSignature) return
    agentSignature = signature
    agentPlan.replaceChildren()
    if (!plan) return
    agentStatus.textContent = plan.error || ('Draft request: ' + plan.state)
    if (plan.result) {
      agentPlan.append(element('p', plan.result.reason),
        action('Review this draft', () => {
          for (const name of ['name', 'channel', 'duration_days', 'cadence_days']) {
            campaignForm.elements.namedItem(name).value = plan.result[name]
          }
          campaignForm.elements.namedItem('goal').value = plan.goal
          campaignForm.elements.namedItem('name').focus()
        }))
    }
  } catch (error) {
    agentStatus.textContent = error.message
  }
}

agent.addEventListener('submit', async event => {
  event.preventDefault()
  const button = agent.querySelector('button')
  button.disabled = true
  try {
    const response = await fetch('/api/plans', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({goal: new FormData(agent).get('goal')})})
    if (!response.ok) throw new Error((await response.json()).error)
    await refreshAgent()
  } catch (error) {
    agentStatus.textContent = error.message
  } finally {
    button.disabled = false
  }
})
capabilities.then(session => {
  if (session?.ai_planner) {
    agent.hidden = false
    refreshAgent()
    setInterval(refreshAgent, 3000)
  }
})
