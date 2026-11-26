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
    await page.getByRole('heading', {name: 'Create a clip'}).waitFor()
    await page.getByText(/up to 8 MiB/).waitFor()
    await page.getByLabel('Source video').setInputFiles(fixture)
    await page.getByLabel('End (seconds)').fill('2')
    await page.getByRole('button', {name: 'Queue render'}).click()
    await page.getByRole('button', {name: 'Preview'}).waitFor()
    const player = page.locator('video')
    await player.evaluate(async video => { video.muted = true; await video.play() })
    await page.waitForFunction(() => document.querySelector('video').currentTime > 0.25)
    const media = new URL(await player.getAttribute('src'), base)
    assert.equal((await fetch(media)).status, 401)
    await page.getByRole('button', {name: 'Sign out'}).click()
    await page.getByRole('heading', {name: 'Sign in'}).waitFor()
    console.log('Render preview passed: password gate, upload, real video playback, private media, sign out.')
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
