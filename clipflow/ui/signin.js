const form = document.getElementById('signin')
form.addEventListener('submit', async event => {
  event.preventDefault()
  const button = form.querySelector('button')
  const status = document.getElementById('login-status')
  button.disabled = true
  try {
    const response = await fetch('/api/session', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.fromEntries(new FormData(form)))
    })
    if (!response.ok) throw new Error((await response.json()).error)
    window.location.replace('/' + window.location.hash)
  } catch (error) {
    status.textContent = error.message || 'Sign-in failed'
  } finally {
    button.disabled = false
  }
})
