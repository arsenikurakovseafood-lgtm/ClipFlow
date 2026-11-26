const campaignForm = document.getElementById('campaign-form')
const campaignStatus = document.getElementById('campaign-status')
const providers = {youtube: 'YouTube Shorts', instagram: 'Instagram Reels', tiktok: 'TikTok'}
let campaignSignature = ''
let workspaceCampaigns = []
let youtubeMetricsEnabled = false

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
  if (!ready.length) {
    const link = element('a', 'Review rendered clips in Content')
    link.href = '#content'
    return link
  }
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
      campaign.target_clips + ' target clips', 'every ' + campaign.cadence_days + ' days',
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
    const eligible = job => !job.campaign_id || job.campaign_id === campaign.id
    controls.append(action('Create clips for this campaign', () => openCampaignStudio(campaign)))
    card.append(scheduleForm(base, ready.filter(eligible)))
    const finished = batches.filter(eligible)
    if (finished.length) card.append(batchScheduleForm(base, finished))
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
  const endpoint = '/api/manual-posts/' + post.id
  if (post.post_url) {
    const link = element('a', 'Open reported post')
    link.href = post.post_url
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
    card.append(element('p', 'Post reported by owner'), link, metricForm(endpoint))
    if (post.channel === 'youtube' && youtubeMetricsEnabled) {
      card.append(action('Read current YouTube statistics', async () => {
        if (await campaignAction(endpoint + '/youtube-metrics')) await refreshInsights()
      }))
    }
  } else if (post.state === 'handed_off') {
    const form = element('form')
    const input = element('input')
    input.name = 'url'
    input.type = 'url'
    input.required = true
    input.maxLength = 500
    const label = element('label', 'Published post URL')
    label.append(input)
    form.append(label, element('button', 'Record post URL'))
    form.addEventListener('submit', async event => {
      event.preventDefault()
      await campaignAction(endpoint + '/record', {url: input.value.trim()})
    })
    card.append(form)
  }
  return card
}

function metricForm(endpoint) {
  const details = element('details')
  details.append(element('summary', 'Add platform metrics'))
  const form = element('form')
  const checkpoint = element('select')
  checkpoint.name = 'hours'
  for (const [hours, label] of [[24, '24 hours'], [72, '72 hours'], [168, '7 days']]) {
    const option = element('option', label)
    option.value = hours
    checkpoint.append(option)
  }
  const windowLabel = element('label', 'Checkpoint')
  windowLabel.append(checkpoint)
  form.append(windowLabel)
  const fields = element('div')
  fields.className = 'campaign-fields'
  for (const metric of ['views', 'likes', 'comments', 'shares', 'saves', 'clicks', 'conversions']) {
    const label = element('label', metric[0].toUpperCase() + metric.slice(1))
    const field = element('input')
    field.name = metric
    field.type = 'number'
    field.min = 0
    field.max = 1000000000
    field.required = metric === 'views'
    label.append(field)
    fields.append(label)
  }
  const button = element('button', 'Save platform metrics')
  form.append(fields, element('small', 'Copy the actual counts from the platform. Leave unavailable counts blank. Saving the same checkpoint replaces it.'), button)
  form.addEventListener('submit', async event => {
    event.preventDefault()
    button.disabled = true
    try {
      const data = Object.fromEntries([...new FormData(form)].filter(([, value]) => value !== '')
        .map(([field, value]) => [field, Number(value)]))
      if (await campaignAction(endpoint + '/metrics', data)) {
        form.reset()
        details.open = false
        await refreshInsights()
      }
    } finally { button.disabled = false }
  })
  details.append(form)
  return details
}

function campaignOptions(select, campaigns) {
  const selected = select.value
  select.replaceChildren(select.options[0], ...campaigns.map(campaign => {
    const option = element('option', campaign.name)
    option.value = campaign.id
    return option
  }))
  select.value = campaigns.some(campaign => campaign.id === selected) ? selected : ''
}

async function refreshCampaigns() {
  try {
    const paths = ['/api/campaigns', '/api/jobs']
    const responses = await Promise.all(paths.map(path => fetch(path)))
    if (responses.some(response => !response.ok)) throw new Error()
    const [data, jobs] = await Promise.all(responses.map(response => response.json()))
    const ready = jobs.filter(job => job.state === 'ready' && job.review === 'approved')
    const batches = jobs.filter(job => {
      if (job.state !== 'prepared') return false
      const clips = jobs.filter(clip => clip.batch_parent === job.id)
      return clips.length && clips.every(clip => clip.state === 'ready' && clip.review === 'approved')
    })
    const signature = JSON.stringify([data, ready.map(job => job.id), batches.map(job => job.id)])
    if (signature === campaignSignature) return
    campaignSignature = signature
    workspaceCampaigns = data.campaigns
    campaignOptions(document.querySelector('#batch-form [name=campaign]'), data.campaigns.filter(campaign => campaign.state === 'active'))
    campaignOptions(document.querySelector('#ledger-form [name=campaign]'), data.campaigns)
    document.getElementById('overview-due').textContent = data.posts.filter(post => post.state === 'due').length
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
      budget_cents: Math.round(Number(values.budget) * 100), workflow: values.workflow,
      target_clips: Number(values.target_clips)
    })) campaignForm.reset()
  } finally { submit.disabled = false }
})
refreshCampaigns()
setInterval(refreshCampaigns, 3000)


const agent = document.getElementById('agent-form')
const agentStatus = document.getElementById('agent-status')
const agentPlan = document.getElementById('agent-plan')
let agentSignature = ''
let showProviderDraft = false

function reviewDraft(goal, draft) {
  for (const [key, value] of Object.entries({...draft, goal})) {
    const field = campaignForm.elements.namedItem(key)
    if (field) field.value = value
  }
  location.hash = 'campaigns'
  window.setTimeout(() => campaignForm.elements.namedItem('name').focus(), 0)
}

function guidedDraft(goal, preset) {
  const duration = goal.match(/\b([1-9]\d?)\s*(?:days?\b|дн(?:я|ей)|суток)/iu)
  const count = goal.match(/\b([1-9]\d?)\s*(?:clips?\b|videos?\b|клип(?:а|ов)?|видео|ролик(?:а|ов)?)/iu)
  const days = Math.min(90, Number(duration?.[1] || 7))
  const clips = Math.min(10, Number(count?.[1] || 3))
  const workflow = ['speech', 'music'].includes(preset) ? preset : 'original'
  const channel = /instagram|инстаграм|reels/iu.test(goal) ? 'instagram'
    : /tiktok|тик.?ток/iu.test(goal) ? 'tiktok' : 'youtube'
  const firstLine = goal.split(/\n|[.!?](?:\s|$)/u)[0].trim()
  return {name: (firstLine || goal).slice(0, 80), duration_days: days, cadence_days: Math.max(1, Math.floor(days / clips)),
    target_clips: clips, workflow, channel, budget: 0}
}

async function refreshAgent() {
  if (!showProviderDraft) return
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
        action('Review this draft', () => reviewDraft(plan.goal, {
          ...guidedDraft(plan.goal, agent.elements.preset.value), ...plan.result
        })))
    }
  } catch (error) {
    agentStatus.textContent = error.message
  }
}

agent.addEventListener('submit', async event => {
  event.preventDefault()
  const button = event.submitter || agent.querySelector('button')
  const {goal, preset} = Object.fromEntries(new FormData(agent))
  if (!goal.trim()) return
  if (button.name !== 'ai') {
    showProviderDraft = false
    const draft = guidedDraft(goal.trim(), preset)
    agentStatus.textContent = 'Guided draft · review before approval'
    const source = {speech: 'Authorized spoken footage', music: 'Authorized footage and track', original: 'Authorized footage, hook and call to action'}[draft.workflow]
    agentPlan.replaceChildren(element('p', `${draft.target_clips} clips over ${draft.duration_days} days · ${providers[draft.channel]} · manual publishing`),
      element('p', `${source}. Estimated provider spend for this draft: €0.`),
      action('Review this draft', () => reviewDraft(goal.trim(), draft)))
    return
  }
  showProviderDraft = true
  button.disabled = true
  try {
    const response = await fetch('/api/plans', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({goal})})
    if (!response.ok) throw new Error((await response.json()).error)
    await refreshAgent()
  } catch (error) {
    agentStatus.textContent = error.message
  } finally {
    button.disabled = false
  }
})
capabilities.then(session => {
  if (session?.youtube_metrics) {
    youtubeMetricsEnabled = true
    document.getElementById('youtube-analytics-status').textContent = 'Public YouTube statistics available for recorded posts.'
    campaignSignature = ''
    refreshCampaigns()
  }
  if (session?.ai_planner) {
    agent.querySelector('button[name=ai]').hidden = false
    document.getElementById('agent-capability').textContent = 'Use guided planning or request an OpenAI draft within your approved planning budget.'
    showProviderDraft = true
    refreshAgent()
    setInterval(refreshAgent, 3000)
  }
})
