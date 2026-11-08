/** The Telegram SDK reads launch data before the app module starts. */
export function applyEntryRoute() {
  const url = new URL(window.location.href);
  const section = url.searchParams.get('section');
  if (section !== 'catalog' && section !== 'suppliers' && section !== 'subscription') return;
  url.searchParams.delete('section');
  url.hash = section === 'catalog' ? '' : '/'+section;
  // Consume this instruction once so later in-app navigation and reload work.
  window.history.replaceState(window.history.state, '', url.toString());
}
