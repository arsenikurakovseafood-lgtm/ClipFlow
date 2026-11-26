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
  const startPreview = 'import sys; from clipflow import render_preview; render_preview.DATA=sys.argv[1]; sys.exit(render_preview.main())'
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
    await batch.getByLabel('Where is your video?').selectOption('file')
    await batch.getByLabel('What are you making?').selectOption('speech')
    await batch.getByLabel('What should the clips achieve?').fill('Persistence and creative courage')
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
    }
    await page.getByRole('navigation').getByRole('link', {name: 'Campaigns'}).click()
    const planner = page.locator('#campaign-form')
    await planner.getByLabel('Name').fill('Persistence campaign')
    await planner.getByLabel('Content goal').fill('Publish short clips manually.')
    await planner.getByRole('button', {name: 'Create plan'}).click()
    await page.getByRole('button', {name: 'Approve'}).click()
    const campaign = page.locator('#campaign-list article')
    await campaign.getByLabel('First batch release').fill('2027-01-01T12:00')
    await campaign.getByRole('button', {name: 'Schedule entire batch'}).click()
    await page.locator('#publication-list article').nth(1).waitFor()
    assert.equal(await page.locator('#publication-list article').count(), 2)
    await page.getByRole('navigation').getByRole('link', {name: 'Studio'}).click()
    await batch.getByLabel('What are you making?').selectOption('visual')
    await batch.getByLabel('Subtitle file').setInputFiles([])
    await batch.getByLabel('What should the clips achieve?').fill('Quick visual edit')
    await batch.getByLabel('Number of clips').fill('1')
    await batch.getByRole('button', {name: 'Create clips'}).click()
    await page.getByRole('navigation').getByRole('link', {name: 'Content'}).click()
    await page.locator('#jobs li').filter({hasText: 'Quick visual edit'})
      .getByRole('button', {name: 'Preview', exact: true}).waitFor()
    await page.getByRole('navigation').getByRole('link', {name: 'Accounts'}).click()
    await page.getByRole('heading', {name: 'Publishing accounts'}).waitFor()
    assert.equal(await page.getByRole('link', {name: 'Open YouTube Studio'}).getAttribute('href'), 'https://studio.youtube.com/')
    await page.getByRole('button', {name: 'Sign out'}).click()
    await page.getByRole('heading', {name: 'Sign in'}).waitFor()
    console.log('Render preview passed: password gate, upload, real video playback, batch selection and playback, private media, sign out.')
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
