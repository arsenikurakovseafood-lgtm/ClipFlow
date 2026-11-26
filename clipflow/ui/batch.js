const batchForm = document.getElementById('batch-form')
const batchMode = batchForm.elements.namedItem('mode')
const batchTrack = document.getElementById('batch-track')
const batchStatus = document.getElementById('batch-status')
let batchKey

function updateBatchMode(session) {
  const music = batchMode.value === 'music'
  batchTrack.hidden = !music
  batchForm.elements.namedItem('music').required = music
  batchForm.elements.namedItem('captions').required = !music && !session.automatic_captions
  document.getElementById('batch-caption-help').textContent = music
    ? 'Optional. Use an SRT or WebVTT file aligned to the source.'
    : session.automatic_captions
      ? 'Attach SRT or WebVTT, or generate captions from source speech with OpenAI.'
      : 'Required in Owner Preview. Attach SRT or WebVTT aligned to the source.'
}

capabilities.then(session => {
  if (!session?.batch_editing) return
  document.getElementById('batch-studio').hidden = false
  updateBatchMode(session)
  batchMode.addEventListener('change', () => updateBatchMode(session))
})
batchForm.addEventListener('input', () => { batchKey = undefined })
batchForm.addEventListener('submit', async event => {
  event.preventDefault()
  const values = new FormData(batchForm)
  const source = values.get('source')
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
        'X-Source-Bytes': String(source.size),
        'X-Music-Bytes': String(music?.size || 0),
        'X-Subtitle-Bytes': String(captions.size),
        'X-Clip-Name': encodeURIComponent(source.name),
        'X-Content-Goal': encodeURIComponent(values.get('goal')),
        'X-Batch-Reference': encodeURIComponent(values.get('reference')),
        'X-Batch-Mode': values.get('mode'),
        'X-Clip-Count': values.get('count'),
        'X-Release-Days': values.get('days'),
        'X-Caption-Style': values.get('style')
      },
      body: new Blob([source, ...(music ? [music] : []), captions])
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
