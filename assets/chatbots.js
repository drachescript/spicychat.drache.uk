(() => {
  const sectionsEl = document.getElementById("bot-sections");
  const pillsEl = document.getElementById("category-pills");
  const searchEl = document.getElementById("bot-search");
  const emptyEl = document.getElementById("empty-state");

  const cats = window.BOT_CATEGORIES || [];
  const bots = window.BOTS || [];

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

  const initials = (name) => name.split(/\s+/).map(x => x[0]).join("").slice(0, 2).toUpperCase();

  function botCard(bot) {
    return `
      <article class="bot-card" data-search="${escapeHtml(`${bot.name} ${bot.title} ${bot.blurb}`.toLowerCase())}">
        <div class="bot-art" aria-hidden="true"><span>${escapeHtml(initials(bot.name))}</span></div>
        <div class="bot-card-body">
          <div class="bot-card-topline">
            <h3>${escapeHtml(bot.name)}</h3>
            ${bot.requested ? '<span class="requested-badge">Requested</span>' : ''}
          </div>
          <p class="bot-title">${escapeHtml(bot.title)}</p>
          <p class="bot-blurb">${escapeHtml(bot.blurb)}</p>
          <a class="chat-button" href="${escapeHtml(bot.url)}" target="_blank" rel="noopener">Open on SpicyChat <span>↗</span></a>
        </div>
      </article>`;
  }

  function itemsFor(cat) {
    if (cat.id === "requested") return bots.filter(bot => bot.requested);
    return bots.filter(bot => bot.category === cat.id);
  }

  function render() {
    const query = searchEl.value.trim().toLowerCase();
    let visibleCount = 0;

    sectionsEl.innerHTML = cats.map(cat => {
      const categoryBots = itemsFor(cat).filter(bot => {
        if (!query) return true;
        return `${bot.name} ${bot.title} ${bot.blurb}`.toLowerCase().includes(query);
      });

      if (!categoryBots.length) return "";
      visibleCount += categoryBots.length;

      return `
        <section class="bot-section" id="${escapeHtml(cat.id)}">
          <div class="section-heading">
            <div>
              <p class="section-kicker">${categoryBots.length} ${categoryBots.length === 1 ? "bot" : "bots"}</p>
              <h2>${escapeHtml(cat.name)}</h2>
            </div>
            <p>${escapeHtml(cat.note)}</p>
          </div>
          <div class="bot-grid">${categoryBots.map(botCard).join("")}</div>
        </section>`;
    }).join("");

    emptyEl.hidden = visibleCount !== 0;
  }

  pillsEl.innerHTML = cats.map(cat => `<a href="#${escapeHtml(cat.id)}">${escapeHtml(cat.name)}</a>`).join("");
  searchEl.addEventListener("input", render);
  render();
})();
