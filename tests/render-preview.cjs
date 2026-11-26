const assert = require('node:assert/strict')
const {execFileSync, spawn} = require('node:child_process')
const {randomBytes} = require('node:crypto')
const {once} = require('node:events')
const {mkdtemp, rm} = require('node:fs/promises')
const {tmpdir} = require('node:os')
const {join} = require('node:path')
const {setTimeout: delay} = require('node:timers/promises')
const {chromium} = require('playwright')

async function main() {
  const root = await mkdtemp(join(tmpdir(), 'clipflow-render-preview-'))
  const port = '34124'
  const base = 'http://localhost:' + port
  const password = randomBytes(32).toString('base64url')
  const executablePath = process.env.CLIPFLOW_CHROMIUM
  // Allow the form to queue a conversion without a provider in this browser fixture.
  const startPreview = [
    'import sys',
    'from clipflow import render_preview',
    'render_preview.DATA = sys.argv[1]',
    'original_settings = render_preview.service_settings',
    'def fixture_settings():',
    '    root, web, worker = original_settings()',
    '    web.update(CLIPFLOW_VIDFETCH_ENABLED="true", CLIPFLOW_VIDFETCH_MONTHLY_JOBS="5")',
    '    return root, web, worker',
    'render_preview.service_settings = fixture_settings',
    'sys.exit(render_preview.main())'
  ].join('\n')
  const server = spawn('python3', ['-c', startPreview, root], {
    env: {...process.env, PORT: port, CLIPFLOW_PREVIEW_PASSWORD: password},
    stdio: 'inherit'
  })
  const exited = once(server, 'exit')
  let browser
  try {
    const fixture = join(root, 'preview-fixture.mp4')
    execFileSync('ffmpeg', ['-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
      'color=c=navy:s=320x180:r=30', '-t', '3', '-c:v', 'libx264', fixture])
    for (let attempt = 0; attempt < 20; attempt++) {
      try {
        if ((await fetch(base + '/healthz')).ok) break
      } catch {
        // The preview can still be listening during startup.
      }
      await delay(250)
    }
    assert.equal((await fetch(base + '/api/jobs')).status, 401)
    browser = await chromium.launch(executablePath ? {executablePath} : {channel: 'chrome'})
    const page = await browser.newPage()
    await page.goto(base)
    await page.getByRole('heading', {name: 'Sign in'}).waitFor()
    assert.equal(await page.getByLabel('Email').isVisible(), false)
    await page.getByLabel('Password').fill('wrong-password-fixture')
    await page.getByRole('button', {name: 'Sign in'}).click()
    await page.getByText('Check your sign-in details').waitFor()
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', {name: 'Sign in'}).click()
    await page.getByRole('navigation').getByRole('link', {name: 'Studio'}).click()
    await page.getByRole('heading', {name: 'Create clips'}).waitFor()
    await page.getByRole('link', {name: 'Trim a single clip manually'}).click()
    await page.getByRole('heading', {name: 'Create a clip'}).waitFor()
    await page.locator('#upload-limits').filter({hasText: /up to 8 MiB/}).waitFor()
    await page.locator('#render').getByLabel('Source video').setInputFiles(fixture)
    await page.getByLabel('End (seconds)').fill('2')
    await page.getByRole('button', {name: 'Queue render'}).click()
    await page.getByRole('navigation').getByRole('link', {name: 'Content'}).click()
    await page.getByRole('button', {name: 'Preview', exact: true}).waitFor()
    const player = page.locator('video')
    await player.evaluate(async video => { video.muted = true; await video.play() })
    await page.waitForFunction(() => document.querySelector('video').currentTime > 0.25)
    const media = new URL(await player.getAttribute('src'), base)
    assert.equal((await fetch(media)).status, 401)
    const batchSource = join(root, 'batch-interview.mp4')
    execFileSync('ffmpeg', ['-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
      'color=c=navy:s=320x180:r=30', '-t', '8', '-c:v', 'libx264', batchSource])
    await page.getByRole('navigation').getByRole('link', {name: 'Studio'}).click()
    const batch = page.locator('#batch-form')
    assert.equal(await batch.getByLabel('Subtitle file').getAttribute('required'), null)
    await batch.getByLabel('Where is your video?').selectOption('link')
    await batch.getByLabel('Video file link').waitFor()
    await batch.getByLabel('Video file link').fill('https://www.youtube.com/playlist?list=fixture')
    await batch.getByLabel('What should the clips achieve?').fill('Preview a clear source error')
    await batch.getByRole('button', {name: 'Create clips'}).click()
    await page.getByText(/Enter a public YouTube video link or a direct Cloudflare R2 file link/).waitFor()
    await page.getByRole('navigation').getByRole('link', {name: 'AI Agent'}).click()
    const agent = page.locator('#agent-form')
    await agent.getByLabel('Describe your campaign').fill('Make 2 clips over 3 days about persistence and creative courage')
    await agent.getByRole('button', {name: 'Prepare a draft'}).click()
    await agent.getByRole('button', {name: 'Review this draft'}).click()
    const planner = page.locator('#campaign-form')
    await planner.getByLabel('Name').fill('Persistence campaign')
    await planner.getByRole('button', {name: 'Create plan'}).click()
    await page.getByRole('button', {name: 'Approve', exact: true}).click()
    const campaign = page.locator('#campaign-list article')
    await campaign.getByRole('button', {name: 'Create clips for this campaign'}).click()
    await batch.getByLabel('Where is your video?').selectOption('file')
    assert.equal(await batch.locator('[name=mode]').inputValue(), 'speech')
    assert.equal(await batch.locator('[name=count]').inputValue(), '2')
    await batch.getByLabel('Upload video').setInputFiles(batchSource)
    await batch.getByLabel('Subtitle file').setInputFiles({
      name: 'fixture.vtt', mimeType: 'text/vtt', buffer: Buffer.from(
        'WEBVTT\n\n00:00.000 --> 00:03.500\nPersistence is a habit.\n\n' +
        '00:04.000 --> 00:07.500\nCourage is doing the work anyway.\n')
    })
    await batch.getByLabel('Number of clips').fill('2')
    await batch.getByLabel('Caption color').selectOption('pink')
    await batch.getByRole('button', {name: 'Create clips'}).click()
    await page.getByRole('navigation').getByRole('link', {name: 'Content'}).click()
    await page.getByText('2 of 2 clips queued for the render worker.').waitFor()
    await page.getByText('Suggested release · day 2 of 3').waitFor()
    for (const title of ['Persistence is a habit.', 'Courage is doing the work anyway.']) {
      const clip = page.locator('#jobs li').filter({hasText: title})
      await clip.getByRole('button', {name: 'Preview', exact: true}).waitFor()
      await clip.getByRole('button', {name: 'Preview', exact: true}).click()
      await player.evaluate(async video => { video.muted = true; await video.play() })
      await page.waitForFunction(() => document.querySelector('video').currentTime > 0.1)
      await clip.getByRole('button', {name: 'Approve clip'}).click()
      await clip.getByText('Review · approved').waitFor()
    }
    await page.getByRole('navigation').getByRole('link', {name: 'Campaigns'}).click()
    await campaign.getByLabel('First batch release').fill('2027-01-01T12:00')
    await campaign.getByRole('button', {name: 'Schedule entire batch'}).click()
    await page.locator('#publication-list article').nth(1).waitFor()
    assert.equal(await page.locator('#publication-list article').count(), 2)
    await page.getByRole('navigation').getByRole('link', {name: 'Studio'}).click()
    await batch.locator('select[name=campaign]').selectOption('')
    await batch.getByLabel('What are you making?').selectOption('original')
    await batch.getByLabel('Where is your video?').selectOption('sample')
    await batch.getByText('Choose a time range', {exact: true}).click()
    await batch.getByRole('textbox', {name: 'From', exact: true}).fill('0:06')
    await batch.getByRole('textbox', {name: 'To', exact: true}).fill('0:18')
    await batch.getByLabel('Subtitle file').setInputFiles([])
    await batch.getByLabel('What should the clips achieve?').fill('Quick visual edit')
    await batch.getByLabel('Opening text').fill('A real on-screen hook')
    await batch.getByRole('textbox', {name: 'Call to action', exact: true}).fill('Watch the next clip')
    await batch.getByLabel('Number of clips').fill('1')
    await batch.getByRole('button', {name: 'Create clips'}).click()
    await page.getByRole('navigation').getByRole('link', {name: 'Content'}).click()
    const sampleBatch = page.locator('#jobs li').filter({hasText: 'Batch: ClipFlow walkthrough sample'})
    await sampleBatch.getByText('Source timecodes · 00:00:06–00:00:18').waitFor()
    const sampleId = await sampleBatch.getAttribute('data-job-id')
    await page.locator(`#jobs li[data-batch-id="${sampleId}"]`)
      .getByRole('button', {name: 'Preview', exact: true}).click()
    await player.evaluate(async video => { video.muted = true; await video.play() })
    await page.waitForFunction(() => document.querySelector('video').currentTime > 0.1)
    const track = join(root, 'authorized-track.wav')
    execFileSync('ffmpeg', ['-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
      'sine=frequency=440', '-t', '4', track])
    await page.getByRole('navigation').getByRole('link', {name: 'Studio'}).click()
    await batch.getByLabel('What are you making?').selectOption('music')
    await batch.getByLabel('What should the clips achieve?').fill('Promote the recovery fixture track')
    await batch.getByLabel('Track audio file').setInputFiles(track)
    await batch.getByLabel('Where is your video?').selectOption('youtube')
    await batch.getByLabel('Video file link').fill('https://www.youtube.com/shorts/abcdefghijk')
    await batch.getByRole('textbox', {name: 'From', exact: true}).fill('12:00')
    await batch.getByRole('textbox', {name: 'To', exact: true}).fill('12:08')
    await batch.getByRole('checkbox', {name: 'I have permission to process and edit this video.'}).check()
    await batch.getByRole('button', {name: 'Create clips'}).click()
    await page.getByText(/Segment conversion queued/).waitFor()
    await page.getByRole('navigation').getByRole('link', {name: 'Content'}).click()
    const recovery = page.locator('.source-recovery')
    await recovery.getByLabel('Replacement video').waitFor()
    await page.getByText('Source timecodes · 00:12:00–00:12:08').waitFor()
    const jobId = (await recovery.getAttribute('id')).replace('replace-source-', '')
    assert.equal((await fetch(base + '/api/batches/' + jobId + '/replace-source', {method: 'POST'})).status, 401)
    await recovery.getByLabel('Or direct Cloudflare R2 file link').fill('https://www.youtube.com/shorts/abcdefghijk')
    await recovery.getByRole('button', {name: 'Replace video and retry'}).click()
    await recovery.getByRole('status').filter({hasText: /enter a direct Cloudflare R2 file link/}).waitFor()
    await recovery.getByLabel('Or direct Cloudflare R2 file link').clear()
    await recovery.getByLabel('Replacement video').setInputFiles(batchSource)
    await recovery.getByRole('button', {name: 'Replace video and retry'}).click()
    const recovered = page.locator('#jobs li').filter({hasText: 'Promote the recovery fixture track'})
    await recovered.getByRole('button', {name: 'Preview', exact: true}).click()
    await player.evaluate(async video => { video.muted = true; await video.play() })
    await page.waitForFunction(() => document.querySelector('video').currentTime > 0.1)
    await page.getByRole('navigation').getByRole('link', {name: 'Accounts'}).click()
    await page.getByRole('heading', {name: 'Publishing accounts'}).waitFor()
    assert.equal(await page.getByRole('link', {name: 'Open YouTube Studio'}).getAttribute('href'), 'https://studio.youtube.com/')
    await page.getByRole('navigation').getByRole('link', {name: 'Studio'}).click()
    await page.route('**/api/session', async route => {
      if (route.request().method() !== 'GET') return route.continue()
      const response = await route.fetch()
      if (!response.ok()) return route.fulfill({response})
      await route.fulfill({status: response.status(), json: {...await response.json(), youtube_converter: false}})
    })
    await page.reload()
    await batch.getByLabel('Where is your video?').selectOption('youtube')
    assert.equal(await batch.getByRole('button', {name: 'Create clips'}).isVisible(), false)
    assert.equal(await batch.getByLabel('Subtitle file').isVisible(), false)
    await batch.getByRole('button', {name: 'Try sample range'}).click()
    assert.equal(await batch.getByRole('textbox', {name: 'From', exact: true}).inputValue(), '0:06')
    assert.equal(await batch.getByRole('button', {name: 'Create clips'}).isEnabled(), true)
    await page.context().clearCookies()
    await page.waitForURL('**/signin#studio')
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', {name: 'Sign in'}).click()
    await page.getByRole('heading', {name: 'Create clips'}).waitFor()
    await page.getByRole('button', {name: 'Sign out'}).click()
    await page.getByRole('heading', {name: 'Sign in'}).waitFor()
    console.log('Render preview passed: password gate, upload, real video playback, batch selection and source recovery, private media, sign out.')
  } finally {
    if (browser) await browser.close()
    server.kill()
    await exited
    await rm(root, {recursive: true, force: true})
  }
}

main().catch(error => {
  console.error(error)
  process.exitCode = 1
})
