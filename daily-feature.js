"use strict";
/**
 * HP Channel — Topic of the Day.
 *
 * Include only completed, published articles here, with working RU/EN links.
 * Sample shape (not an actual article):
 * {status:"published", category:{ru:"...",en:"..."}, image:"https://...",
 *  alt:{ru:"...",en:"..."}, ru:{title:"...",summary:"...",url:"article.html"},
 *  en:{title:"...",summary:"...",url:"article-en.html"}}
 *
 * Unwritten drafts and placeholders must never appear here.
 * The same article is selected for everyone by UTC date, once per day.
 */
const publishedArticles = [];

(function selectDailyFeature() {
  const feature = document.getElementById("daily-feature");
  if (!feature) return;
  const lang = document.documentElement.lang === "en" ? "en" : "ru";
  const safeInternalLink = /^[a-z0-9_-]+\.html(?:#[a-z0-9_-]+)?$/i;
  const eligible = publishedArticles.filter((article) =>
    article.status === "published" &&
    article.ru && article.en &&
    safeInternalLink.test(article.ru.url) && safeInternalLink.test(article.en.url) &&
    article.ru.title && article.en.title
  );
  if (eligible.length === 0) return; // Keep the empty-state message.

  const day = Math.floor(Date.now() / 86400000);
  const article = eligible[day % eligible.length];
  const localized = article[lang];
  const link = document.createElement("a");
  link.className = "story-link";
  link.href = localized.url;
  if (article.image && /^https:\/\//i.test(article.image)) {
    const image = document.createElement("img");
    image.className = "photo";
    image.src = article.image;
    image.alt = (article.alt && article.alt[lang]) || "";
    link.appendChild(image);
  }
  const category = document.createElement("div");
  category.className = "kicker";
  const label = lang === "ru" ? "Главная тема дня" : "Topic of the Day";
  const section = article.category && article.category[lang];
  category.textContent = section ? label + " · " + section : label;
  link.appendChild(category);
  const heading = document.createElement("h2");
  heading.textContent = localized.title;
  link.appendChild(heading);
  if (localized.summary) {
    const summary = document.createElement("p");
    summary.textContent = localized.summary;
    link.appendChild(summary);
  }
  feature.replaceChildren(link);
  feature.classList.remove("daily-feature-empty");
})();
