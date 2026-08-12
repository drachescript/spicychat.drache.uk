(() => {
  const sectionsEl = document.getElementById("bot-sections");
  const pillsEl = document.getElementById("category-pills");
  const searchEl = document.getElementById("bot-search");
  const emptyEl = document.getElementById("empty-state");

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

  const initials = (name) => String(name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .map(part => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  let cats = [];
  let bots = [];

  function art(bot) {
    const fallback = `<span class="bot-art-fallback">${escapeHtml(initials(bot.name))}</span>`;
    if (!bot.image) return `<div class="bot-art">${fallback}</div>`;

    return `
      <div class="bot-art">
        ${fallback}
        <img src="${escapeHtml(bot.image)}" alt="${escapeHtml(bot.name)}" loading="lazy" referrerpolicy="no-referrer">
      </div>`;
  }

  function botCard(bot) {
    return `
      <article class="bot-card">
        ${art(bot)}
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

  function bindImageFallbacks() {
    document.querySelectorAll(".bot-art img").forEach(img => {
      img.addEventListener("error", () => img.remove(), { once: true });
    });
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

    bindImageFallbacks();
    emptyEl.hidden = visibleCount !== 0;
  }

  async function load() {
    try {
      const response = await fetch("../assets/bots.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      cats = Array.isArray(data.categories) ? data.categories : [];
      bots = Array.isArray(data.bots) ? data.bots : [];

      pillsEl.innerHTML = cats
        .map(cat => `<a href="#${escapeHtml(cat.id)}">${escapeHtml(cat.name)}</a>`)
        .join("");

      searchEl.addEventListener("input", render);
      render();
    } catch (error) {
      console.error("Couldn't load bots.json", error);
      sectionsEl.innerHTML = '<p class="load-error">Couldn\'t load the bot list. Try refreshing the page.</p>';
    }
  }

  load();
})();
