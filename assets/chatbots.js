(() => {
  const sectionsEl = document.getElementById("bot-sections");
  const pillsEl = document.getElementById("category-pills");
  const searchEl = document.getElementById("bot-search");
  const emptyEl = document.getElementById("empty-state");
  const viewTabs = [...document.querySelectorAll("[data-view]")];

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
  let currentView = "all";

  function readViewFromUrl() {
    const requested = new URLSearchParams(window.location.search).get("view");
    return requested === "categories" ? "categories" : "all";
  }

  function setView(view, push = false) {
    currentView = view === "categories" ? "categories" : "all";

    viewTabs.forEach(tab => {
      const active = tab.dataset.view === currentView;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-current", active ? "page" : "false");
    });

    pillsEl.hidden = currentView !== "categories";

    if (push) {
      const url = new URL(window.location.href);
      if (currentView === "all") url.searchParams.delete("view");
      else url.searchParams.set("view", "categories");
      history.pushState({ view: currentView }, "", url);
    }

    render();
  }

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
          <a class="chat-button" href="${escapeHtml(bot.url)}" target="_blank" rel="noopener">Open <span>↗</span></a>
        </div>
      </article>`;
  }

  function matches(bot, query) {
    if (!query) return true;
    return `${bot.name} ${bot.title} ${bot.blurb}`.toLowerCase().includes(query);
  }

  function categoryItems(cat) {
    if (cat.id === "requested") return bots.filter(bot => bot.requested);
    return bots.filter(bot => bot.category === cat.id);
  }

  function sectionMarkup({ id, name, note, items, kicker }) {
    if (!items.length) return "";
    return `
      <section class="bot-section" id="${escapeHtml(id)}">
        <div class="section-heading">
          <div>
            <p class="section-kicker">${escapeHtml(kicker || `${items.length} ${items.length === 1 ? "bot" : "bots"}`)}</p>
            <h2>${escapeHtml(name)}</h2>
          </div>
          ${note ? `<p>${escapeHtml(note)}</p>` : ""}
        </div>
        <div class="bot-grid">${items.map(botCard).join("")}</div>
      </section>`;
  }

  function renderAll(query) {
    const favorites = bots
      .filter(bot => Number.isFinite(Number(bot.favoriteOrder)))
      .sort((a, b) => Number(a.favoriteOrder) - Number(b.favoriteOrder))
      .filter(bot => matches(bot, query));

    const all = bots.filter(bot => matches(bot, query));

    return {
      count: all.length,
      html: [
        sectionMarkup({
          id: "personal-favorites",
          name: "Personal Favorites",
          note: "the ones I'd probably point you at first if you don't know where to start.",
          items: favorites,
          kicker: "my picks"
        }),
        sectionMarkup({
          id: "all-bots",
          name: "All Bots",
          note: "everything I've got up right now, newest ideas mixed in with older ones.",
          items: all
        })
      ].join("")
    };
  }

  function renderCategories(query) {
    let count = 0;
    const html = cats.map(cat => {
      const items = categoryItems(cat).filter(bot => matches(bot, query));
      if (!items.length) return "";
      count += items.length;
      return sectionMarkup({ id: cat.id, name: cat.name, note: cat.note, items });
    }).join("");
    return { count, html };
  }

  function bindImageFallbacks() {
    document.querySelectorAll(".bot-art img").forEach(img => {
      img.addEventListener("error", () => img.remove(), { once: true });
    });
  }

  function render() {
    const query = searchEl.value.trim().toLowerCase();
    const result = currentView === "categories"
      ? renderCategories(query)
      : renderAll(query);

    sectionsEl.innerHTML = result.html;
    bindImageFallbacks();
    emptyEl.hidden = result.count !== 0;
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

      viewTabs.forEach(tab => {
        tab.addEventListener("click", event => {
          event.preventDefault();
          setView(tab.dataset.view, true);
        });
      });

      window.addEventListener("popstate", () => setView(readViewFromUrl(), false));
      searchEl.addEventListener("input", render);
      setView(readViewFromUrl(), false);
    } catch (error) {
      console.error("Couldn't load bots.json", error);
      sectionsEl.innerHTML = '<p class="load-error">Couldn\'t load the bot list. Try refreshing the page.</p>';
    }
  }

  load();
})();
