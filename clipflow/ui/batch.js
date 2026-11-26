const batchForm = document.getElementById('batch-form')
const batchMode = batchForm.elements.namedItem('mode')
const batchTrack = document.getElementById('batch-track')
const batchStatus = document.getElementById('batch-status')
let batchKey
let sampleKey
let batchSession
let submittingBatch = false
const sourceKind = batchForm.elements.namedItem('sourceKind')
const createClips = batchForm.querySelector('button[type=submit]')
const runSample = document.getElementById('try-segment')
function updateSourceKind() {
  const converter = sourceKind.value === 'youtube'
  const sample = sourceKind.value === 'sample'
  const link = converter || sourceKind.value === 'link'
  const file = sourceKind.value === 'file'
  document.getElementById('batch-source-file').hidden = !file
  document.getElementById('batch-source-url').hidden = !link
  document.getElementById('batch-sample-note').hidden = !sample
  batchForm.elements.namedItem('source').required = file
  batchForm.elements.namedItem('sourceUrl').required = link
  const range = document.getElementById('batch-segment')
  if (converter) range.open = true
  document.getElementById('source-permission').hidden = !converter
  for (const field of ['segmentStart', 'segmentEnd', 'authorized']) {
    batchForm.elements.namedItem(field).required = converter
  }
  document.getElementById('youtube-source-help').textContent = converter
    ? 'Paste the link to a YouTube video or Short.' : 'Paste the direct HTTPS link to an R2 video file.'
  const blocked = converter && !batchSession?.youtube_converter
  document.getElementById('converter-availability').hidden = !blocked
  createClips.hidden = blocked
  createClips.disabled = submittingBatch || blocked
  if (batchSession) updateBatchMode(batchSession)
}
sourceKind.addEventListener('change', () => {
  batchForm.elements.segmentStart.value = ''
  batchForm.elements.segmentEnd.value = ''
  document.getElementById('batch-segment').open = false
  batchKey = undefined
  updateSourceKind()
})
runSample.addEventListener('click', () => {
  const values = new FormData()
  const example = {sourceKind: 'sample', mode: 'visual', segmentStart: '0:06', segmentEnd: '0:18',
    count: '2', days: '1', style: 'white', goal: 'ClipFlow walkthrough', campaign: '', reference: '',
    creative: 'standard', hook: '', cta: ''}
  for (const [field, value] of Object.entries(example)) values.set(field, value)
  values.set('captions', new Blob())
  if (batchSession?.automatic_captions) values.set('automaticCaptions', 'on')
  void submitBatch(values, runSample)
})

function updateBatchMode(session) {
  const music = batchMode.value === 'music'
  const speech = batchMode.value === 'speech'
  const sample = sourceKind.value === 'sample'
  const automatic = batchForm.elements.namedItem('automaticCaptions')
  automatic.disabled = !session.automatic_captions
  automatic.checked = !automatic.disabled && !music
  document.getElementById('caption-controls').hidden = automatic.disabled
  document.getElementById('caption-language').hidden = automatic.disabled || !automatic.checked || sample || session.paid_captions
  document.getElementById('caption-availability').textContent = speech && automatic.disabled && !sample
    ? 'Spoken highlights need captions. Add them in Advanced settings.' : ''
  batchTrack.hidden = !music
  const original = batchMode.value === 'original'
  batchForm.elements.namedItem('hook').required = original
  batchForm.elements.namedItem('cta').required = original
  if (original) {
    document.getElementById('studio-advanced').open = true
    document.getElementById('creative-options').open = true
  }
  batchForm.elements.namedItem('music').required = music && !sample
  batchForm.elements.namedItem('captions').required = speech && !session.automatic_captions && !sample
  if (batchForm.elements.namedItem('captions').required) document.getElementById('studio-advanced').open = true
  document.getElementById('batch-caption-help').textContent = !speech || sample
    ? 'Optional. Use an SRT or WebVTT file aligned to the source.'
    : session.automatic_captions
      ? 'Attach SRT or WebVTT, or generate captions from source speech with OpenAI.'
      : 'Required in Owner Preview. Attach SRT or WebVTT aligned to the source.'
  if (sourceKind.value === 'youtube') {
    document.getElementById('batch-caption-help').textContent += ' Use timestamps from the full YouTube video.'
  }
}

capabilities.then(session => {
  if (!session) {
    document.getElementById('batch-unavailable').hidden = false
    return
  }
  batchSession = session
  batchForm.hidden = false
  updateSourceKind()
  batchMode.addEventListener('change', () => updateBatchMode(session))
  batchForm.elements.automaticCaptions.addEventListener('change', event => {
    document.getElementById('caption-language').hidden = !event.target.checked || sourceKind.value === 'sample' || session.paid_captions
  })
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
  await submitBatch(new FormData(batchForm), createClips)
})

async function submitBatch(values, button) {
  if (submittingBatch || !batchSession) return
  const example = button === runSample
  const status = example ? document.getElementById('sample-status') : batchStatus
  const converter = values.get('sourceKind') === 'youtube'
  const sourceUrl = converter || values.get('sourceKind') === 'link' ? values.get('sourceUrl').trim() : ''
  const sample = values.get('sourceKind') === 'sample'
  const source = sample || sourceUrl ? null : values.get('source')
  const music = values.get('mode') === 'music' ? values.get('music') : null
  const captions = values.get('captions')
  status.textContent = example ? 'Submitting the sample…' : 'Staging source and preparing the batch…'
  submittingBatch = true
  createClips.disabled = true
  runSample.disabled = true
  button.setAttribute('aria-busy', 'true')
  button.textContent = 'Submitting…'
  const key = example ? (sampleKey ||= crypto.randomUUID()) : (batchKey ||= crypto.randomUUID())
  try {
    const bundle = new Blob([...(source ? [source] : []), ...(music ? [music] : []), captions])
    const response = await studioFetch('/api/batches', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/octet-stream',
        'Idempotency-Key': key,
        'X-Source-Bytes': String(source?.size || 0),
        'X-Music-Bytes': String(music?.size || 0),
        'X-Subtitle-Bytes': String(captions.size),
        'X-Clip-Name': encodeURIComponent(sample ? 'ClipFlow walkthrough sample' : source?.name || 'Linked video'),
        'X-Content-Goal': encodeURIComponent(values.get('goal')),
        'X-Batch-Reference': encodeURIComponent(values.get('reference')),
        'X-Batch-Source-URL': encodeURIComponent(sourceUrl),
        'X-Segment-Start': values.get('segmentStart').trim(),
        'X-Segment-End': values.get('segmentEnd').trim(),
        'X-Caption-Language': sample ? 'en' : values.get('captionLanguage'),
        'X-Source-Authorized': converter && values.has('authorized') ? '1' : '0',
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
      body: batchSession.direct_upload ? null : bundle,
      signal: AbortSignal.timeout(45000)
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error)
    if (batchSession.direct_upload) await uploadPrivateMedia(result, bundle)
    status.textContent = converter ? 'Segment conversion queued. Open Content to track your clips.' : sourceUrl
      ? 'Video import queued. Open Content to check whether the source was retrieved.'
      : 'Batch queued. Open Content to track rendering.'
    if (example) {
      sampleKey = undefined
      location.hash = 'content'
    }
    await refresh()
  } catch (error) {
    status.textContent = error.name === 'TimeoutError' ? 'The server did not confirm the upload. Check Content before trying again.'
      : error.message || 'Batch upload failed.'
  } finally {
    submittingBatch = false
    button.removeAttribute('aria-busy')
    button.textContent = example ? 'Run sample now' : 'Create clips'
    createClips.disabled = sourceKind.value === 'youtube' && !batchSession?.youtube_converter
    runSample.disabled = false
  }
}
