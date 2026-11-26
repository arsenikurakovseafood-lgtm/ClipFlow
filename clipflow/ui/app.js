const byId = id => document.getElementById(id)
const form = byId('render')
const player = byId('player')
let displayedJobs = ''
let selected
let requestKey

async function uploadPrivateMedia(result, body) {
  if (!result.url) return
  const upload = await fetch(result.url, {method: 'PUT', headers: result.headers, body, redirect: 'error'})
  if (!upload.ok) throw new Error('Private storage rejected the upload.')
  const complete = await fetch('/api/uploads/' + result.id + '/complete', {method: 'POST'})
  if (!complete.ok) throw new Error((await complete.json()).error)
}

function show(job) {
  if (selected === job.id) return
  selected = job.id
  player.src = '/media/' + job.id
  byId('download').href = player.src + '?download=1'
  byId('preview').hidden = false
}

function sourceRecovery(job) {
  const existing = byId('replace-source-' + job.id)
  if (existing) return existing
  const form = document.createElement('form')
  form.id = 'replace-source-' + job.id
  form.className = 'source-recovery'
  form.innerHTML = `
    <small>Your track and clip settings are saved while this batch is available.</small>
    <label>Replacement video <input type="file" name="video" accept=".mp4,.mov,.webm"></label>
    <label>Or direct Cloudflare R2 file link <input type="url" name="url" maxlength="2400"></label>
    <button type="submit">Replace video and retry</button>
    <small role="status"></small>`
  const button = form.querySelector('button')
  const status = form.querySelector('[role=status]')
  if (job.trim_end !== null) {
    form.querySelector('small').textContent = 'Use an MP4 already cut to the selected timecodes. Your track and settings are saved.'
  }
  const video = form.elements.video
  if (!job.file_replacement) video.closest('label').hidden = true
  form.addEventListener('submit', async event => {
    event.preventDefault()
    const file = job.file_replacement ? video.files[0] : null
    const url = form.elements.url.value.trim()
    if (Boolean(file) === Boolean(url)) {
      status.textContent = job.file_replacement ? 'Choose one video file or enter one direct R2 file link.'
        : 'Enter a direct R2 video file link.'
      return
    }
    button.disabled = true
    status.textContent = 'Submitting replacement…'
    try {
      const mediaTypes = {mp4: 'video/mp4', mov: 'video/quicktime', webm: 'video/webm'}
      const options = file
        ? {body: file, headers: {'Content-Type': mediaTypes[file.name.split('.').pop().toLowerCase()] || file.type}}
        : {headers: {'X-Replacement-URL': encodeURIComponent(url)}}
      const response = await fetch('/api/batches/' + job.id + '/replace-source', {method: 'POST', ...options})
      if (!response.ok) throw new Error((await response.json()).error)
      await refresh()
    } catch (error) {
      status.textContent = error.message || 'Could not replace the video. Try again.'
      button.disabled = false
    }
  })
  return form
}

function clipReview(job) {
  const controls = document.createElement('div')
  controls.className = 'review-controls'
  const status = document.createElement('small')
  status.setAttribute('role', 'status')
  status.textContent = 'Review · ' + job.review
  for (const [review, label] of [['approved', 'Approve clip'], ['rejected', 'Reject clip']]) {
    if (review === job.review) continue
    const button = document.createElement('button')
    button.type = 'button'
    button.textContent = label
    button.addEventListener('click', async () => {
      button.disabled = true
      try {
        const response = await fetch('/api/clips/' + job.id + '/review', {method: 'POST',
          headers: {'Content-Type': 'application/json'}, body: JSON.stringify({review})})
        if (!response.ok) throw new Error((await response.json()).error)
        await refresh()
        await refreshCampaigns()
      } catch (error) { status.textContent = error.message }
      finally { button.disabled = false }
    })
    controls.append(button)
  }
  controls.append(status)
  return controls
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
      row.dataset.jobId = job.id
      if (job.batch_parent) row.dataset.batchId = job.batch_parent
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
      if (job.trim_end !== null) {
        const interval = document.createElement('small')
        const timecode = seconds => new Date(seconds * 1000).toISOString().slice(11, 19)
        interval.textContent = 'Source timecodes · ' + timecode(job.trim_start) + '–' + timecode(job.trim_end)
        row.append(interval)
      }
      if (job.state === 'ready') row.append(clipReview(job))
      if (job.source_replaceable) row.append(sourceRecovery(job))
      if (job.release_day) {
        const release = document.createElement('small')
        release.textContent = 'Suggested release · day ' + job.release_day + ' of ' + job.release_days
        row.append(release)
      }
      if (job.reference) {
        const reference = document.createElement('a')
        reference.textContent = 'Source reference'
        reference.href = job.reference
        reference.target = '_blank'
        reference.rel = 'noopener noreferrer'
        row.append(reference)
      }
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
  button.disabled = true
  status.textContent = 'Uploading to cloud storage…'
  requestKey ||= crypto.randomUUID()
  const mime = {mov: 'video/quicktime', webm: 'video/webm', mp4: 'video/mp4'}
  try {
    const session = await capabilities
    if (!session) throw new Error('Reload the studio to reconnect.')
    if (source.size > session.upload_limit_mib * 1024 * 1024 || end - start < 1 || end - start > session.clip_limit_seconds) {
      throw new Error('Choose a video up to ' + session.upload_limit_mib + ' MiB and a clip between 1 and ' + session.clip_limit_seconds + ' seconds.')
    }
    const type = mime[source.name.split('.').pop().toLowerCase()] || source.type
    const headers = {
      'Idempotency-Key': requestKey,
      'X-Clip-Name': encodeURIComponent(source.name),
      'X-Clip-Auto-Captions': values.has('autoCaptions') ? '1' : '0',
      'X-Clip-Start': String(start), 'X-Clip-End': String(end),
      'X-Clip-Cues': encodeURIComponent(JSON.stringify(caption ? [{start, end, text: caption}] : []))
    }
    if (session.direct_upload) {
      const reservation = await fetch('/api/uploads', {
        method: 'POST', headers: {...headers, 'X-Upload-Size': String(source.size), 'X-Upload-Mime': type}
      })
      const result = await reservation.json()
      if (!reservation.ok) throw new Error(result.error)
      await uploadPrivateMedia(result, source)
    } else {
      const response = await fetch('/api/jobs', {
        method: 'POST', body: source, headers: {...headers, 'Content-Type': type}
      })
      if (!response.ok) throw new Error((await response.json()).error)
    }
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

const signOut = document.getElementById('sign-out')
const capabilities = fetch('/api/session').then(async response => {
  if (!response.ok) return null
  const session = await response.json()
  document.getElementById('upload-limits').textContent =
    'Authorized MP4, MOV or WebM · up to ' + session.upload_limit_mib + ' MiB · clip up to ' + session.clip_limit_seconds + ' s'
  signOut.hidden = !session.sign_out
  document.getElementById('auto-option').hidden = !session.automatic_captions
  return session
}).catch(() => null)
signOut.addEventListener('click', async () => {
  const response = await fetch('/api/session/logout', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
  })
  if (response.ok) window.location.replace('/signin')
})
