const screens = {
  overview: 'overview', studio: 'batch-studio', 'batch-studio': 'batch-studio',
  trim: 'trim', content: 'content', campaigns: 'campaigns', accounts: 'accounts',
  agent: 'agent', revenue: 'revenue', settings: 'settings'
}
function openScreen() {
  const requested = window.location.hash.slice(1)
  const target = Object.hasOwn(screens, requested) ? screens[requested] : 'overview'
  for (const screen of document.querySelectorAll('[data-screen]')) screen.hidden = screen.id !== target
  for (const link of document.querySelectorAll('.sidebar nav a')) {
    const mapped = screens[link.hash.slice(1)]
    if (mapped === target || (mapped === 'batch-studio' && target === 'trim')) {
      link.setAttribute('aria-current', 'page')
    } else {
      link.removeAttribute('aria-current')
    }
  }
}
openScreen()
window.addEventListener('hashchange', openScreen)
