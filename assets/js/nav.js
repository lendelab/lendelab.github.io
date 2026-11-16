document.documentElement.classList.add('js');
(() => {
  const mast = document.querySelector('.mast');
  const name = mast.querySelector('.mast__name');
  const row = mast.querySelector('.mast__row');
  const dockLink = mast.querySelector('.mast__dock');
  const bar = mast.querySelector('.bar');
  const fold = document.querySelector('.fold');
  const shown = (el) => el.offsetParent !== null && !el.closest('[inert]');

  // phone menus of the link row and of the bar
  const sheet = document.getElementById('sheet');
  const panels = [
    { layer: row, zone: [row], toggle: row.querySelector('.mast__toggle'), panel: row.querySelector('.mast__links'), set: (open) => row.toggleAttribute('data-open', open) },
    { layer: bar, zone: [bar, sheet], toggle: bar.querySelector('.bar__menu'), panel: sheet, set: (open) => { sheet.hidden = !open; } },
  ];
  const isOpen = (p) => p.toggle.getAttribute('aria-expanded') === 'true';
  const setPanel = (p, open) => { p.toggle.setAttribute('aria-expanded', String(open)); p.set(open); };
  panels.forEach(p => {
    p.toggle.addEventListener('click', () => setPanel(p, !isOpen(p)));
    p.panel.querySelectorAll('a').forEach(a => a.addEventListener('click', () => setPanel(p, false)));
  });
  document.addEventListener('click', (e) => { panels.forEach(p => { if (isOpen(p) && !p.panel.contains(e.target) && !p.toggle.contains(e.target)) setPanel(p, false); }); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') panels.forEach(p => { if (isOpen(p)) { setPanel(p, false); p.toggle.focus(); } }); });

  // move focus to the matching control when its part becomes inert
  const handOver = (had, zone, fallback) => {
    if (!had) return;
    const href = had.getAttribute('href');
    const twin = (href && zone.flatMap(z => [...z.querySelectorAll(`a[href="${href}"]`)]).find(shown))
      || fallback || zone.flatMap(z => [...z.querySelectorAll('a[href], button')]).find(shown);
    if (twin) twin.focus({ preventScroll: true });
  };
  const settle = () => requestAnimationFrame(() => requestAnimationFrame(() => mast.classList.remove('is-settling')));

  // docked: the nameplate has scrolled away
  let docked = null, frosted = null;
  new IntersectionObserver(([e]) => {
    const next = !e.isIntersecting;
    if (next !== docked) {
      docked = next;
      const had = [name, dockLink].includes(document.activeElement) ? document.activeElement : null;
      mast.classList.toggle('is-docked', next);
      dockLink.inert = !next; name.inert = next;
      if (had && had.inert) handOver(had, next ? [frosted ? bar : row] : [mast]);
    }
    settle();
  }).observe(name);

  // frosted: past the fold
  const frost = (next) => {
    if (next === frosted) return;
    frosted = next;
    const [from, to] = next ? panels : [panels[1], panels[0]];
    const had = from.zone.some(z => z.contains(document.activeElement)) ? document.activeElement : null;
    const wasOpen = isOpen(from);
    mast.classList.toggle('is-frosted', next);
    to.layer.inert = false; from.layer.inert = true;
    if (wasOpen) setPanel(from, false);
    if (wasOpen && shown(to.toggle)) setPanel(to, true);
    handOver(had, to.zone, had === from.toggle && shown(to.toggle) ? to.toggle : null);
  };
  let io, h = 0;
  const watch = () => {
    if (bar.offsetHeight === h) return;
    h = bar.offsetHeight;
    if (io) io.disconnect();
    io = new IntersectionObserver(([e]) => { frost(!e.isIntersecting); settle(); }, { rootMargin: `-${h}px 0px 0px 0px` });
    io.observe(fold);
  };
  watch();
  window.addEventListener('resize', watch, { passive: true });
})();
