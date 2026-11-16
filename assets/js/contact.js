(() => {
  const form = document.querySelector('form.form');
  if (!form) return;
  const t = form.dataset;
  const status = form.querySelector('.form__status');
  const button = form.querySelector('button[type="submit"]');
  const fields = [...form.querySelectorAll('input, textarea')];
  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  form.noValidate = true;

  const problem = (el) => {
    const v = el.value.trim();
    if (el.required && !v) return t.required;
    if (el.type === 'email' && v && !emailRe.test(v)) return t.badEmail;
    return '';
  };
  const show = (el, msg) => {
    const err = document.getElementById(`${el.id}-err`);
    if (msg) el.setAttribute('aria-invalid', 'true'); else el.removeAttribute('aria-invalid');
    err.textContent = msg;
  };
  fields.forEach((el) => {
    el.addEventListener('blur', () => { el.dataset.touched = '1'; show(el, problem(el)); });
    el.addEventListener('input', () => { if (el.dataset.touched) show(el, problem(el)); });
  });

  const say = (state, text, email) => {
    status.dataset.state = state;
    status.textContent = text;
    if (email) {
      const a = document.createElement('a');
      a.href = `mailto:${email}`;
      a.textContent = email;
      status.append(' ', a, '.');
    }
  };

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (form.dataset.busy) return;
    let first = null;
    fields.forEach((el) => {
      el.dataset.touched = '1';
      const msg = problem(el);
      show(el, msg);
      if (msg && !first) first = el;
    });
    if (first) { first.focus(); return; }
    form.dataset.busy = '1';
    button.setAttribute('aria-disabled', 'true');
    button.textContent = t.sending;
    status.removeAttribute('data-state');
    status.textContent = '';
    try {
      const body = new URLSearchParams(new FormData(form));
      await Promise.all([
        fetch(form.action, { method: 'POST', mode: 'no-cors', body }),
        new Promise((r) => setTimeout(r, 300)),
      ]);
      form.reset();
      fields.forEach((el) => { delete el.dataset.touched; el.removeAttribute('aria-invalid'); });
      say('sent', t.sent);
    } catch {
      say('failed', t.failed, t.email);
    } finally {
      delete form.dataset.busy;
      button.removeAttribute('aria-disabled');
      button.textContent = t.send;
    }
  });
})();
