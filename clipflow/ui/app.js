const byId = id => document.getElementById(id)
const form = byId('render')
const player = byId('player')
let displayedJobs = ''
let selected
let requestKey

function show(job) {
  if (selected === job.id) return
  selected = job.id
  player.src = '/media/' + job.id
  byId('download').href = player.src + '?download=1'
  byId('preview').hidden = false
}

async function refresh() {
  try {
    const response = await fetch('/api/jobs')
    if (!response.ok) throw new Error()
    const jobs = await response.json()
    byId('library-status').textContent = jobs.length ? '' : 'Your rendered clips will appear here.'
    const signature = JSON.stringify(jobs)
    if (displayedJobs === signature) return
    displayedJobs = signature
    byId('ready').textContent = jobs.filter(job => job.state === 'ready').length
    byId('failed').textContent = jobs.filter(job => job.state === 'failed').length
    byId('active').textContent = jobs.filter(job => ['uploading', 'queued', 'running'].includes(job.state)).length
    byId('jobs').replaceChildren(...jobs.map(job => {
      const row = document.createElement('li')
      const name = document.createElement('strong')
      name.textContent = job.name
      row.append(name)
      if (job.state === 'ready') {
        const preview = document.createElement('button')
        preview.type = 'button'
        preview.textContent = 'Preview'
        preview.addEventListener('click', () => show(job))
        row.append(preview)
        if (!selected) show(job)
      }
      const detail = document.createElement('small')
      detail.textContent = job.state === 'ready' ? 'Ready · ' + job.elapsed.toFixed(2) + ' s render'
        : (job.error || job.state[0].toUpperCase() + job.state.slice(1))
      row.append(detail)
      return row
    }))
  } catch {
    byId('library-status').textContent = 'Could not reach the render library. Retrying…'
  }
}

form.addEventListener('input', () => { requestKey = undefined })
form.addEventListener('submit', async event => {
  event.preventDefault()
  const values = new FormData(form)
  const source = values.get('source')
  const start = Number(values.get('start'))
  const end = Number(values.get('end'))
  const caption = values.get('caption').trim()
  const status = byId('status')
  const button = form.querySelector('button')
  if (source.size > 25 * 1024 * 1024 || end - start < 1 || end - start > 60) {
    status.textContent = 'Choose a video up to 25 MiB and a clip between 1 and 60 seconds.'
    return
  }
  button.disabled = true
  status.textContent = 'Uploading to cloud storage…'
  requestKey ||= crypto.randomUUID()
  const mime = {mov: 'video/quicktime', webm: 'video/webm', mp4: 'video/mp4'}
  try {
    const response = await fetch('/api/jobs', {
      method: 'POST', body: source,
      headers: {
        'Content-Type': mime[source.name.split('.').pop().toLowerCase()] || source.type,
        'Idempotency-Key': requestKey,
        'X-Clip-Name': encodeURIComponent(source.name),
        'X-Clip-Start': String(start), 'X-Clip-End': String(end),
        'X-Clip-Cues': encodeURIComponent(JSON.stringify(caption ? [{start, end, text: caption}] : []))
      }
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error)
    status.textContent = 'Accepted. You can close this tab while the worker renders.'
    await refresh()
  } catch (error) {
    status.textContent = error.message || 'Upload failed. Try again.'
  } finally {
    button.disabled = false
  }
})
refresh()
setInterval(refresh, 1600)
