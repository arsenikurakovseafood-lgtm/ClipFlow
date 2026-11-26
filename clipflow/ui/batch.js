const batchForm = document.getElementById('batch-form')
const batchMode = batchForm.elements.namedItem('mode')
const batchTrack = document.getElementById('batch-track')
const batchStatus = document.getElementById('batch-status')
let batchKey
const sourceKind = batchForm.elements.namedItem('sourceKind')
function updateSourceKind() {
  const link = sourceKind.value === 'link'
  document.getElementById('batch-source-file').hidden = link
  document.getElementById('batch-source-url').hidden = !link
  batchForm.elements.namedItem('source').required = !link
  batchForm.elements.namedItem('sourceUrl').required = link
}
sourceKind.addEventListener('change', updateSourceKind)

function updateBatchMode(session) {
  const music = batchMode.value === 'music'
  const speech = batchMode.value === 'speech'
  const automatic = batchForm.elements.namedItem('automaticCaptions')
  automatic.disabled = !session.automatic_captions
  if (!automatic.disabled) automatic.checked = true
  document.getElementById('caption-availability').textContent = automatic.disabled
    ? 'Automatic subtitles are paused here. Uploading a subtitle file is optional for Quick clips and Music promos.'
    : music ? 'Generate subtitles from the uploaded track’s vocals.' : 'Generate subtitles from speech in the source video.'
  batchTrack.hidden = !music
  batchForm.elements.namedItem('music').required = music
  batchForm.elements.namedItem('captions').required = speech && !session.automatic_captions
  document.getElementById('batch-caption-help').textContent = !speech
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
  batchForm.hidden = false
  updateBatchMode(session)
  batchMode.addEventListener('change', () => updateBatchMode(session))
})
batchForm.addEventListener('input', () => { batchKey = undefined })
batchForm.addEventListener('submit', async event => {
  event.preventDefault()
  const values = new FormData(batchForm)
  const sourceUrl = values.get('sourceKind') === 'link' ? values.get('sourceUrl').trim() : ''
  const source = sourceUrl ? null : values.get('source')
  const music = values.get('mode') === 'music' ? values.get('music') : null
  const captions = values.get('captions')
  const button = batchForm.querySelector('button')
  batchStatus.textContent = 'Staging source and preparing the batch…'
  button.disabled = true
  batchKey ||= crypto.randomUUID()
  try {
    if (sourceUrl && /(?:^|\.)(?:youtube\.com|youtu\.be)$/.test(new URL(sourceUrl).hostname)) {
      throw new Error('A YouTube page cannot supply the video file. Put that link in the reference field and upload your authorized original.')
    }
    const response = await fetch('/api/batches', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/octet-stream',
        'Idempotency-Key': batchKey,
        'X-Source-Bytes': String(source?.size || 0),
        'X-Music-Bytes': String(music?.size || 0),
        'X-Subtitle-Bytes': String(captions.size),
        'X-Clip-Name': encodeURIComponent(source?.name || 'Linked video'),
        'X-Content-Goal': encodeURIComponent(values.get('goal')),
        'X-Batch-Reference': encodeURIComponent(values.get('reference')),
        'X-Batch-Source-URL': encodeURIComponent(sourceUrl),
        'X-Batch-Mode': values.get('mode'),
        'X-Clip-Count': values.get('count'),
        'X-Release-Days': values.get('days'),
        'X-Caption-Style': values.get('style'),
        'X-Batch-Auto-Captions': values.has('automaticCaptions') && !captions.size ? '1' : '0'
      },
      body: new Blob([...(source ? [source] : []), ...(music ? [music] : []), captions])
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error)
    batchStatus.textContent = 'Batch accepted. Watch the render library for clips.'
    await refresh()
  } catch (error) {
    batchStatus.textContent = error.message || 'Batch upload failed.'
  } finally {
    button.disabled = false
  }
})
