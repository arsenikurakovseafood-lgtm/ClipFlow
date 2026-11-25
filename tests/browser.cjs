const assert = require('node:assert/strict')
const { execFileSync, spawn } = require('node:child_process')
const { mkdir, mkdtemp, readFile, rm, writeFile } = require('node:fs/promises')
const { tmpdir } = require('node:os')
const { join, resolve } = require('node:path')
const { once } = require('node:events')
const { setTimeout: delay } = require('node:timers/promises')
const { chromium } = require('playwright')

const executablePath = process.env.CLIPFLOW_CHROMIUM
const port = 34123
const base = 'http://127.0.0.1:' + port

function start(module, state, ...options) {
  return spawn('python3', ['-m', module, state, ...options], {stdio: 'inherit'})
}

async function stop(process) {
  if (process.exitCode !== null || process.signalCode !== null) return
  const exited = once(process, 'exit')
  process.kill()
  await exited
}

async function waitForServer() {
  for (let attempt = 0; attempt < 40; attempt++) {
    try {
      const response = await fetch(base + '/api/jobs')
      if (response.ok) return response.json()
    } catch {
      // The child process may still be binding its port.
    }
    await delay(250)
  }
  throw new Error('Cloud demo did not start')
}

async function main() {
  const temp = await mkdtemp(join(tmpdir(), 'clipflow-browser-'))
  const state = join(temp, 'media')
  const evidence = resolve(process.argv[2] ?? join(temp, 'evidence'))
  const source = join(temp, 'synthetic-cloud-fixture.mp4')
  let server, worker, browser
  try {
    await mkdir(evidence, {recursive: true})
    execFileSync('ffmpeg', ['-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
      'color=c=0x26382e:size=960x540:rate=30', '-f', 'lavfi', '-i',
      'sine=frequency=330', '-t', '5', '-vf', 'drawgrid=w=60:h=60:t=1:c=white@0.12',
      '-c:v', 'libx264', '-c:a', 'aac', source])
    server = start('clipflow.web', state, '--port', String(port))
    assert.deepEqual(await waitForServer(), [])
    browser = await chromium.launch(executablePath ? {executablePath} : {channel: 'chrome'})
    const page = await browser.newPage({viewport: {width: 1400, height: 1000}})
    await page.goto(base)
    await page.getByText('Your rendered clips will appear here.').waitFor()
    await page.getByLabel('Source video').setInputFiles(source)
    await page.getByLabel('Optional caption').fill('Synthetic cloud render')
    await page.getByRole('button', {name: 'Queue render'}).click()
    await page.getByText(/Accepted/).waitFor()
    await page.close()
    const queued = await waitForServer()
    assert.equal(queued.length, 1)
    assert.equal(queued[0].state, 'queued')

    // Replace the web process before any worker is started.
    await stop(server)
    server = start('clipflow.web', state, '--port', String(port))
    assert.equal((await waitForServer())[0].id, queued[0].id)
    worker = start('clipflow.worker', state)

    const desktop = await browser.newPage({viewport: {width: 1400, height: 1000}})
    await desktop.goto(base)
    await desktop.getByRole('button', {name: 'Preview'}).waitFor()
    await desktop.locator('video').evaluate(async video => {
      video.muted = true
      await video.play()
    })
    await desktop.waitForFunction(() => document.querySelector('video').currentTime > 0.5)
    assert.deepEqual(await desktop.locator('video').evaluate(video => {
      video.pause()
      return [video.videoWidth, video.videoHeight, video.duration]
    }), [720, 1280, 4])
    const stream = await desktop.locator('video').getAttribute('src')
    const range = await desktop.request.get(new URL(stream, base).href, {headers: {Range: 'bytes=0-31'}})
    assert.equal(range.status(), 206)
    assert.equal((await range.body()).length, 32)
    const download = await desktop.getByRole('link', {name: 'Download MP4'}).getAttribute('href')
    assert.equal(download, base + stream + '?download=1')
    await desktop.screenshot({path: join(evidence, 'owner-desktop.png'), fullPage: true})

    const mobile = await browser.newPage({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true})
    await mobile.goto(base)
    await mobile.getByRole('button', {name: 'Preview'}).waitFor()
    assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await mobile.screenshot({path: join(evidence, 'owner-mobile.png'), fullPage: true})

    const planner = desktop.locator('#campaign-form')
    await planner.getByLabel('Name').fill('Synthetic release')
    await planner.getByLabel('Content goal').fill('Post a short teaser using the fixture')
    await planner.getByRole('button', {name: 'Create plan'}).click()
    await desktop.getByRole('button', {name: 'Approve'}).click()
    const campaign = desktop.locator('#campaign-list article')
    await campaign.getByLabel('Manual publishing time').fill('2020-01-01T12:00')
    await campaign.getByRole('button', {name: 'Schedule manual handoff'}).click()
    await desktop.getByRole('button', {name: 'Mark handed off'}).waitFor()
    await campaign.getByRole('button', {name: 'Pause'}).click()
    await desktop.locator('#publication-list').getByText(/on hold/).waitFor()
    await campaign.getByRole('button', {name: 'Resume'}).click()
    await desktop.getByRole('button', {name: 'Mark handed off'}).click()
    await desktop.locator('#publication-list').getByText(/handed off/).waitFor()
    await desktop.locator('#campaigns').screenshot({path: join(evidence, 'owner-campaigns.png')})

    const body = await readFile(source)
    const bad = await fetch(base + '/api/jobs', {
      method: 'POST', body,
      headers: {'Content-Type': 'video/mp4', 'Idempotency-Key': crypto.randomUUID(),
        'X-Clip-Name': 'out-of-range-fixture.mp4', 'X-Clip-Start': '3', 'X-Clip-End': '8'}
    })
    assert.equal(bad.status, 202)
    await desktop.getByText('Source or clip could not be processed. Check the video and clip range.').waitFor()
    const report = '# ClipFlow browser evidence\n\nSynthetic source only. Verified actual FFmpeg rendering, ' +
      'browser closure before worker start, job persistence across web restart, 720 × 1280 MP4 playback, ' +
      '206 byte-range streaming, explicit download control, mobile layout, campaign approval, pause/resume, manual publishing handoff and a visible failed job.\n'
    await writeFile(join(evidence, 'verification.md'), report)
    console.log(report)
  } finally {
    if (browser) await browser.close()
    if (worker) await stop(worker)
    if (server) await stop(server)
    await rm(temp, {recursive: true, force: true})
  }
}

main().catch(error => {
  console.error(error)
  process.exitCode = 1
})
