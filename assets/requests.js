(() => {
  const CONFIG_URL = '/assets/data/requests.json';
  const DEFAULTS = {
    status: 'open',
    ageGateVersion: 'v1',
    discord: { username: '@dragongraf', invite: 'https://discord.gg/XTMdWvuVSU' },
    apiUrl: 'https://spicychat-requests-api.dragongraf.workers.dev/request',
    simplePreferences: { usually: [], depends: [], notes: [] },
    detailedPreferences: { generallyInto: [], curious: [] },
  };

  let config = DEFAULTS;
  let lastRequestId = '';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function storageKey(version) {
    return `dragonRequests18Plus:${version || 'v1'}`;
  }

  function showPage() {
    const gate = $('#age-gate');
    const content = $('#request-page-content');
    if (gate) gate.hidden = true;
    if (content) content.hidden = false;
    document.body.classList.remove('age-gate-open');
  }

  function showGate() {
    const gate = $('#age-gate');
    const content = $('#request-page-content');
    if (content) content.hidden = true;
    if (gate) {
      gate.hidden = false;
      document.body.classList.add('age-gate-open');
      setTimeout(() => $('#age-yes')?.focus(), 0);
    }
  }

  function initAgeGate() {
    let accepted = false;
    try {
      accepted = localStorage.getItem(storageKey(config.ageGateVersion)) === 'accepted';
    } catch {}
    if (accepted) showPage();
    else showGate();

    $('#age-yes')?.addEventListener('click', () => {
      try { localStorage.setItem(storageKey(config.ageGateVersion), 'accepted'); } catch {}
      showPage();
    });
    $('#age-no')?.addEventListener('click', () => {
      window.location.href = '/chatbots/';
    });
  }

  function statusLabel(status) {
    switch ((status || '').toLowerCase()) {
      case 'limited': return 'Requests: LIMITED';
      case 'paused': return 'Requests: PAUSED';
      default: return 'Requests: OPEN';
    }
  }

  function applyConfig() {
    const status = (config.status || 'open').toLowerCase();
    const pill = $('#request-status-pill');
    if (pill) {
      pill.textContent = statusLabel(status);
      pill.className = `request-status request-status-${status}`;
    }

    const invite = config.discord?.invite || DEFAULTS.discord.invite;
    ['#discord-hero-link', '#discord-inline-link', '#discord-side-link'].forEach((selector) => {
      const el = $(selector);
      if (el) el.href = invite;
    });

    const username = config.discord?.username || DEFAULTS.discord.username;
    $$('[data-discord-username]').forEach((el) => { el.textContent = username; });

    if (status === 'paused') {
      const submit = $('#submit-request');
      if (submit) {
        submit.disabled = true;
        submit.textContent = 'Requests are paused';
      }
      setFormStatus('Requests are paused right now. You can still copy the form and message me on Discord.', 'warning', true);
    }
  }

  function renderTags(target, items) {
    const root = $(target);
    if (!root) return;
    root.innerHTML = '';
    (items || []).forEach((item) => {
      const span = document.createElement('span');
      span.className = 'preference-tag';
      span.textContent = item;
      root.append(span);
    });
  }

  function renderPreferences() {
    renderTags('#simple-usually', config.simplePreferences?.usually);
    renderTags('#simple-depends', config.simplePreferences?.depends);
    renderTags('#detailed-into', config.detailedPreferences?.generallyInto);
    renderTags('#detailed-curious', config.detailedPreferences?.curious);

    const notes = $('#simple-notes');
    if (notes) {
      notes.innerHTML = '';
      (config.simplePreferences?.notes || []).forEach((note) => {
        const p = document.createElement('p');
        p.textContent = note;
        notes.append(p);
      });
    }
  }

  function initPreferenceTabs() {
    $$('[data-pref-view]').forEach((button) => {
      button.addEventListener('click', () => {
        const detailed = button.dataset.prefView === 'detailed';
        $('#preferences-simple').hidden = detailed;
        $('#preferences-detailed').hidden = !detailed;
        $$('[data-pref-view]').forEach((other) => {
          const active = other === button;
          other.classList.toggle('active', active);
          other.setAttribute('aria-selected', active ? 'true' : 'false');
        });
      });
    });
  }

  function selectedValue(name) {
    return $(`input[name="${name}"]:checked`)?.value || '';
  }

  function syncContactFields() {
    const method = selectedValue('contactType') || 'discord';
    const discordWrap = $('#discord-contact-fields');
    const emailWrap = $('#email-contact-fields');
    const discord = $('#discordUsername');
    const email = $('#email');
    const isDiscord = method === 'discord';
    if (discordWrap) discordWrap.hidden = !isDiscord;
    if (emailWrap) emailWrap.hidden = isDiscord;
    if (discord) discord.required = isDiscord;
    if (email) email.required = !isDiscord;
  }

  function syncAdultConfirm() {
    const rating = $('#contentRating')?.value || 'either';
    const wrap = $('#adult-confirm-wrap');
    const confirm = $('#adultConfirm');
    const needed = rating !== 'sfw';
    if (wrap) wrap.hidden = !needed;
    if (confirm) {
      confirm.required = needed;
      if (!needed) confirm.checked = false;
    }
  }

  function initDynamicFields() {
    $$('input[name="contactType"]').forEach((input) => input.addEventListener('change', syncContactFields));
    $('#contentRating')?.addEventListener('change', syncAdultConfirm);
    syncContactFields();
    syncAdultConfirm();

    $$('textarea[maxlength], input[maxlength]').forEach((field) => {
      const counter = document.querySelector(`[data-count-for="${field.id}"]`);
      if (!counter) return;
      const update = () => { counter.textContent = String(field.value.length); };
      field.addEventListener('input', update);
      update();
    });
  }

  function payloadFromForm() {
    return {
      contactType: selectedValue('contactType'),
      discordUsername: $('#discordUsername')?.value.trim() || '',
      email: $('#email')?.value.trim() || '',
      requestType: $('#requestType')?.value || '',
      character: $('#character')?.value.trim() || '',
      fandom: $('#fandom')?.value.trim() || '',
      idea: $('#idea')?.value.trim() || '',
      userRole: $('#userRole')?.value.trim() || '',
      dynamic: $('#dynamic')?.value.trim() || '',
      contentRating: $('#contentRating')?.value || 'either',
      kinks: $('#kinks')?.value.trim() || '',
      hardNos: $('#hardNos')?.value.trim() || '',
      flexibility: selectedValue('flexibility'),
      extra: $('#extra')?.value.trim() || '',
    };
  }

  function validateForm() {
    const form = $('#character-request-form');
    if (!form) return false;
    syncContactFields();
    syncAdultConfirm();
    if (!form.reportValidity()) return false;
    return true;
  }

  function discordCopyText(requestId = '') {
    const p = payloadFromForm();
    const lines = [];
    const add = (label, value) => {
      if (!value) return;
      lines.push(`**${label}:** ${value}`);
    };
    lines.push('**Bot request**');
    if (requestId) add('Request ID', requestId);
    add('Contact', p.contactType === 'discord' ? p.discordUsername : p.email);
    add('Type', p.requestType);
    add('Content', p.contentRating === 'either' ? 'Either / you decide' : p.contentRating.toUpperCase());
    add('Character', p.character);
    add('Fandom', p.fandom);
    if (p.idea) lines.push(`\n**Main idea**\n${p.idea}`);
    if (p.userRole) lines.push(`\n**{{user}}**\n${p.userRole}`);
    if (p.dynamic) lines.push(`\n**Dynamic**\n${p.dynamic}`);
    if (p.kinks) lines.push(`\n**Kinks / themes**\n${p.kinks}`);
    if (p.hardNos) lines.push(`\n**Hard no's**\n${p.hardNos}`);
    add('How closely', p.flexibility);
    if (p.extra) lines.push(`\n**Anything else**\n${p.extra}`);
    return lines.join('\n');
  }

  async function copyText(value) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      const area = document.createElement('textarea');
      area.value = value;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.append(area);
      area.select();
      let copied = false;
      try { copied = document.execCommand('copy'); } catch {}
      area.remove();
      return copied;
    }
  }

  function setFormStatus(message, type = 'info', persistent = false) {
    const box = $('#form-status');
    if (!box) return;
    box.textContent = message;
    box.className = `form-status form-status-${type}`;
    box.hidden = false;
    if (!persistent) {
      clearTimeout(setFormStatus.timer);
      setFormStatus.timer = setTimeout(() => {
        if (!box.classList.contains('form-status-success')) box.hidden = true;
      }, 7000);
    }
  }

  function showSuccess(requestId, discordPosted) {
    lastRequestId = requestId || '';
    const card = $('#request-success-card');
    if (card) card.hidden = false;
    const idEl = $('#success-request-id');
    if (idEl) idEl.textContent = requestId ? `${requestId} saved.` : 'Request saved.';
    const copy = $('#success-copy');
    if (copy) {
      copy.textContent = discordPosted === false
        ? 'The backup was saved, but the Discord delivery had a problem. Keep the request ID and message me if needed.'
        : 'It was saved to the backup database and sent to my private request channel. Keep the ID if you want to ask me about it later.';
    }
  }

  async function submitRequest(event) {
    event.preventDefault();
    if (!validateForm()) return;
    if ((config.status || 'open').toLowerCase() === 'paused') {
      setFormStatus('Requests are paused right now. You can still copy the form for Discord.', 'warning', true);
      return;
    }

    const button = $('#submit-request');
    const original = button?.innerHTML || '';
    if (button) {
      button.disabled = true;
      button.textContent = 'Sending…';
    }
    setFormStatus('Saving your request…', 'info', true);

    try {
      const response = await fetch(config.apiUrl || DEFAULTS.apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payloadFromForm()),
      });
      let data = {};
      try { data = await response.json(); } catch {}

      if (!response.ok || !data.ok) {
        const errors = Array.isArray(data.errors) ? data.errors.join(' ') : (data.error || 'The request could not be sent.');
        throw new Error(errors);
      }

      showSuccess(data.requestId, data.discordPosted);
      if (data.discordPosted === false) {
        setFormStatus(`${data.requestId || 'Your request'} was saved, but Discord delivery failed. The backup is safe.`, 'warning', true);
      } else {
        setFormStatus(`${data.requestId || 'Your request'} was saved and sent.`, 'success', true);
      }
      $('#request-success-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (error) {
      setFormStatus(error?.message || 'Something went wrong while sending the request.', 'error', true);
    } finally {
      if (button) {
        button.disabled = false;
        button.innerHTML = original;
      }
    }
  }

  function initCopyButtons() {
    $('#copy-discord')?.addEventListener('click', async () => {
      if (!validateForm()) return;
      const ok = await copyText(discordCopyText(lastRequestId));
      setFormStatus(ok ? 'Copied the request for Discord.' : 'Could not copy automatically.', ok ? 'success' : 'error');
    });
    $('#copy-request-id')?.addEventListener('click', async () => {
      if (!lastRequestId) return;
      const ok = await copyText(lastRequestId);
      setFormStatus(ok ? `Copied ${lastRequestId}.` : 'Could not copy the request ID.', ok ? 'success' : 'error');
    });
    $('#copy-success-request')?.addEventListener('click', async () => {
      const ok = await copyText(discordCopyText(lastRequestId));
      setFormStatus(ok ? 'Copied the request for Discord.' : 'Could not copy automatically.', ok ? 'success' : 'error');
    });
  }

  async function loadConfig() {
    try {
      const response = await fetch(CONFIG_URL, { cache: 'no-store' });
      if (!response.ok) throw new Error('config');
      config = { ...DEFAULTS, ...(await response.json()) };
    } catch {
      config = DEFAULTS;
    }
  }

  async function init() {
    await loadConfig();
    initAgeGate();
    applyConfig();
    renderPreferences();
    initPreferenceTabs();
    initDynamicFields();
    initCopyButtons();
    $('#character-request-form')?.addEventListener('submit', submitRequest);
  }

  init();
})();
