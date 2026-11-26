const batchForm = document.getElementById('batch-form')
const batchMode = batchForm.elements.namedItem('mode')
const batchTrack = document.getElementById('batch-track')
const batchStatus = document.getElementById('batch-status')
let batchKey
let batchSession
const sourceKind = batchForm.elements.namedItem('sourceKind')
function updateSourceKind() {
  const link = sourceKind.value === 'link'
  const file = sourceKind.value === 'file'
  document.getElementById('batch-source-file').hidden = !file
  document.getElementById('batch-source-url').hidden = !link
  document.getElementById('batch-sample-note').hidden = sourceKind.value !== 'sample'
  batchForm.elements.namedItem('source').required = file
  batchForm.elements.namedItem('sourceUrl').required = link
  if (batchSession) updateBatchMode(batchSession)
}
sourceKind.addEventListener('change', updateSourceKind)

function updateBatchMode(session) {
  const music = batchMode.value === 'music'
  const speech = batchMode.value === 'speech'
  const sample = sourceKind.value === 'sample'
  const automatic = batchForm.elements.namedItem('automaticCaptions')
  automatic.disabled = !session.automatic_captions || sample
  automatic.checked = !automatic.disabled
  document.getElementById('caption-availability').textContent = sample
    ? (music ? 'The sample soundtrack has no vocals.' : 'The sample includes authored subtitles.') : automatic.disabled
    ? 'Automatic subtitles are paused here. Uploading a subtitle file is optional for Quick clips and Music promos.'
    : music ? 'Generate subtitles from the uploaded track’s vocals.' : 'Generate subtitles from speech in the source video.'
  batchTrack.hidden = !music
  const original = batchMode.value === 'original'
  batchForm.elements.namedItem('hook').required = original
  batchForm.elements.namedItem('cta').required = original
  if (original) document.getElementById('creative-options').open = true
  batchForm.elements.namedItem('music').required = music && !sample
  batchForm.elements.namedItem('captions').required = speech && !session.automatic_captions && !sample
  document.getElementById('batch-caption-help').textContent = !speech || sample
    ? 'Optional. Use an SRT or WebVTT file aligned to the source.'
    : session.automatic_captions
      ? 'Attach SRT or WebVTT, or generate captions from source speech with OpenAI.'
      : 'Required in Owner Preview. Attach SRT or WebVTT aligned to the source.'
}

capabilities.then(session => {
  if (!session?.batch_editing) {
    document.getElementById('batch-unavailable').hidden = false
    return
  }
  batchSession = session
  batchForm.hidden = false
  updateSourceKind()
  batchMode.addEventListener('change', () => updateBatchMode(session))
})
function openCampaignStudio(campaign) {
  if (!campaign) return
  batchForm.elements.campaign.value = campaign.id
  batchMode.value = campaign.workflow
  batchMode.dispatchEvent(new Event('change'))
  batchForm.elements.goal.value = campaign.goal.slice(0, 500)
  batchForm.elements.count.value = campaign.target_clips
  batchForm.elements.days.value = Math.min(30, campaign.duration_days)
  batchKey = undefined
  location.hash = 'studio'
}
batchForm.elements.campaign.addEventListener('change', () => {
  openCampaignStudio(workspaceCampaigns.find(campaign => campaign.id === batchForm.elements.campaign.value))
})
batchForm.addEventListener('input', () => { batchKey = undefined })
batchForm.addEventListener('submit', async event => {
  event.preventDefault()
  const values = new FormData(batchForm)
  const sourceUrl = values.get('sourceKind') === 'link' ? values.get('sourceUrl').trim() : ''
  const sample = values.get('sourceKind') === 'sample'
  const source = sample || sourceUrl ? null : values.get('source')
  const music = values.get('mode') === 'music' ? values.get('music') : null
  const captions = values.get('captions')
  const button = batchForm.querySelector('button')
  batchStatus.textContent = 'Staging source and preparing the batch…'
  button.disabled = true
  batchKey ||= crypto.randomUUID()
  try {
    const response = await fetch('/api/batches', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/octet-stream',
        'Idempotency-Key': batchKey,
        'X-Source-Bytes': String(source?.size || 0),
        'X-Music-Bytes': String(music?.size || 0),
        'X-Subtitle-Bytes': String(captions.size),
        'X-Clip-Name': encodeURIComponent(sample ? 'ClipFlow walkthrough sample' : source?.name || 'Linked video'),
        'X-Content-Goal': encodeURIComponent(values.get('goal')),
        'X-Batch-Reference': encodeURIComponent(values.get('reference')),
        'X-Batch-Source-URL': encodeURIComponent(sourceUrl),
        'X-Batch-Sample': sample ? '1' : '0',
        'X-Batch-Mode': values.get('mode'),
        'X-Campaign-ID': values.get('campaign'),
        'X-Creative-Format': values.get('creative'),
        'X-Creative-Hook': encodeURIComponent(values.get('hook')),
        'X-Creative-CTA': encodeURIComponent(values.get('cta')),
        'X-Clip-Count': values.get('count'),
        'X-Release-Days': values.get('days'),
        'X-Caption-Style': values.get('style'),
        'X-Batch-Auto-Captions': values.has('automaticCaptions') && !captions.size ? '1' : '0'
      },
      body: new Blob([...(source ? [source] : []), ...(music ? [music] : []), captions])
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error)
    batchStatus.textContent = sourceUrl
      ? 'Video import queued. Open Content to check whether the source was retrieved.'
      : 'Batch queued. Open Content to track rendering.'
    await refresh()
  } catch (error) {
    batchStatus.textContent = error.message || 'Batch upload failed.'
  } finally {
    button.disabled = false
  }
})
