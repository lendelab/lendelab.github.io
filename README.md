# LendeLab website

This repository builds the website of LendeLab (Lenguaje en neurodegeneración), a research group of the Universidad de Salamanca, with Hugo 0.170.0. Spanish is served at the root and English under `/en/`. GitHub Pages publishes the site at https://lendelab.github.io/.

## Build and preview

`hugo server` starts a local preview at http://localhost:1313/ that reloads on every change. `hugo --minify` writes the finished site to `public/`. The build needs Hugo 0.170.0 and nothing else; there is no Node toolchain.

`python tests/check.py public` runs the layout check on a finished build. It needs Playwright 1.62.0 and its three browsers (`python -m pip install playwright==1.62.0` and `python -m playwright install chromium firefox webkit`). The check serves `public/` on a local port, reads the page list from the built sitemaps and loads every page at 320, 375, 414, 768, 959, 960, 1280 and 1440 px in Chromium, Firefox and WebKit. It fails on horizontal overflow, on navigation links, buttons, footer links and icon links broken over two lines, on a phone menu that does not open, does not span the viewport, has a target under 44 px or does not return focus on Escape, on any request to another site except `api.fontshare.com` and `cdn.fontshare.com`, and on hreflang links that are not reciprocal. A second argument limits the engines, for example `python tests/check.py public chromium`.

## Where the content lives

All content is data; the templates hold no copy except the interface labels.

- `data/site.yaml`: group name, contact address, footer lines, the group description, the facts the home page adds to its project and resource plates, the contact and data-protection texts, the contact form settings and the GoatCounter code.
- `data/members/<slug>.yaml`: one file per member, with position, funding label, affiliation, biography, research lines, doctoral thesis, education, profile links and up to three selected publication ids. The `order` field sets the order of the member index.
- `data/lines/<slug>.yaml`: the four research lines, with their text and topics.
- `data/projects/<slug>.yaml`: projects; `kind` places each one under «dirigidos», «participación» or «anteriores».
- `data/resources/<slug>.yaml`: the Corpus Quijote and the FONEMA corpus and atlas.
- `data/collaborations.yaml`: the partner institutions.
- `data/outreach/<yyyy-mm-dd>-<slug>.yaml`: one file per outreach item.
- `data/theses.yaml`: theses supervised by members whose authors are not members, such as Elisa Suárez Caramés's thesis of 2026.
- `data/publications/`: the group list, the members' additions and the rejected works (see Publications below).
- `static/img/members/`: member photos. Hugo crops each one to a square and writes 240 px and full-size WebP copies; the originals are not published.
- `i18n/es.yaml` and `i18n/en.yaml`: interface labels in both languages.
- `content/es/` and `content/en/`: one `_index.md` per section, holding only the page title. The member and line pages are generated from `data/` by the content adapters `content/*/members/_content.gotmpl` and `content/*/lines/_content.gotmpl`.

Every text field has a Spanish and an English version (`_es` and `_en`). When an English field is empty, the English page shows the Spanish text and marks it `lang="es"`. Spanish section slugs (`/miembros/`, `/lineas/` and so on) and English ones (`/en/members/`, `/en/research-lines/`) are set by the permalinks in `hugo.toml`.

Some files carry optional fields beyond the common ones:

- projects: `pi_role_es` and `pi_role_en`, because the role reads «Investigadora principal» or «Investigador principal» according to the person; `member_notes`, a list of `{member, note_es, note_en}` printed in parentheses after that member's name, so DEMEALEN reads «Jordi Just Alcaraz (tesis doctoral vinculada)», and when any note is present the members are separated by semicolons;
- outreach items: `venue_en`; `people_note_es` and `people_note_en`, the text that follows the participants («con Filipa M. B. Lã», «(docente)», «con otros miembros de LinGAP», «en el stand de LinGAP»), printed after a comma, or after a space when it opens with a parenthesis; `people_and`, which joins the last participant with «y» (or «e») and «and» instead of a comma; `source_es` and `source_en`, the name of the source printed as the text of the item's link (without them the link shows the web address);
- collaborations: `url_label_es` and `url_label_en`, the text of the main link («Sitio web» / «Website» when empty); `more_urls`, further links as `{url, label_es, label_en}`, so the Université de Lille entry keeps both addresses;
- resources: `value_en` on fields and `cite_en`, because the English values and the English citation differ from the Spanish ones;
- `data/theses.yaml`, and the `group`, `home`, `contact` and `entries` blocks of `data/site.yaml`.

## Editing with Pages CMS

`.pages.yml` declares one entry per data file or folder, with typed fields: selects for enumerations, references for member and line slugs, rich text only for biographies and long texts, and image fields that upload into `static/img/members`. Fields that accept either a member slug or a plain name (supervisors, principal investigators, outreach participants) are text fields: a slug links the person's page, any other text is printed as written. Each member's additions file is its own entry, because those files are lists. `data/orcid/` is not declared, so the CMS never edits it. Saving in Pages CMS commits to `main`, and the commit triggers the deploy workflow.

## Publications

- `data/orcid/<slug>.json` is generated every week by `scripts/orcid_fetch.py` from each member's ORCID record and is never edited by hand.
- `data/publications/extra/<slug>.yaml` holds the works members add through Pages CMS. On a member's page these are merged with the ORCID works, deduplicated by DOI and then by normalised title and year; an addition wins over the ORCID version of the same work. Works of type presentation and poster are listed under «Comunicaciones», the rest under «Publicaciones», newest year first.
- `data/publications/group.yaml` is the curated group list shown on the publications page, on the home page (the three newest) and on each line page (the works whose `members` include a member of that line).
- The weekly job proposes new group works as a pull request on the branch «propuestas-publicaciones»; merging the pull request accepts the works.
- Rejected works go in `data/publications/rejected.yaml` with a reason, through `python scripts/orcid_candidates.py reject ID --reason TEXT`.
- Errors in ORCID data are fixed at the source, in the member's ORCID record, and reach the site with the next weekly fetch.

Citations follow APA 7: «y» (or «e» before a name that starts with the sound /i/) and «En» on Spanish pages, «&» and «In» on English pages; DOIs print as https://doi.org/ links; page ranges take an en dash; works with 21 or more authors list the first 19, an ellipsis and the last author. Titles are read as inline Markdown, so `*…*` inside a title prints in italics, and a title in a language other than the page's carries a `lang` attribute.

## Deployment

`.github/workflows/deploy.yml` runs on every push to `main` and on manual dispatch. It installs Hugo 0.170.0 from the release archive and verifies its checksum, writes `data/updated.yaml` with the date of the last commit that touched each member's data file, additions file or ORCID file, builds with `hugo --minify`, runs the layout check in the three engines, and publishes `public/` with the GitHub Pages actions. It shares the concurrency group `pages` with `.github/workflows/orcid.yml`, so the two never deploy at once, and the ORCID workflow runs the same date step before its own build. The member pages print that date as «Última actualización»; `data/updated.yaml` is not committed.

## Design

`assets/css/tokens.css` holds the design tokens (colour, type, spacing, motion), `assets/css/site.css` the stylesheet and `assets/js/nav.js` the header script. Inner pages share the home page's slab fold, wave ornament, bands and footer, with the page title at the display size bottom left.

The sage palette is switched on with one line in `hugo.toml`: `palette = "sage"` under `[params]` (the default is `"teal"`). It loads `assets/css/palette-sage.css` after the default tokens. It is a build setting, not a visitor control.

Outreach items are listed newest first. An item dated by year only is stored with 31 December and `date_precision: year`, and is listed after the dated items of its year; an item dated by month is listed after the dated items of its month. «Próximamente» shows while an item marked `upcoming` has not passed at build time. A member page lists under «Proyectos en curso» the projects that name the member as principal investigator or member and have not ended at build time, so DEMEALEN, which ended on 31 August 2026, appears on no member page. On member pages the biography runs first at reading width, followed by research lines, thesis and education in equal columns; the projects and supervised theses lists flow into two columns.

## Contact form and visitor counter

The contact form is rendered only when `data/site.yaml` has a `form_action` (the Google Form's `/formResponse` address) and the entry ids under `entries` for `nombre`, `correo`, `asunto` and `mensaje` (`institucion` is optional). Without them the contact page shows the email address alone. The form posts with `fetch` in `no-cors` mode, so the page cannot read Google's reply: it reports success when the request leaves the browser and shows the email address when the request fails. Without JavaScript the form posts directly to Google. JavaScript runs only in the navigation and on the contact page.

GoatCounter is switched on by writing the site code in `goatcounter` in `data/site.yaml`. Every page then loads the script-free pixel `https://<code>.goatcounter.com/count?p=<path>`; while the code is empty no pixel is rendered.

Every page loads one font from another host, Cabinet Grotesk: its stylesheet from `api.fontshare.com` and its font files from `cdn.fontshare.com`, the servers of the Indian Type Foundry (ITF). Each visit therefore sends the visitor's IP address and browser headers to ITF. The site sends no other request to another host while the GoatCounter code is empty, and the contact form contacts Google only when a visitor submits it.

## Licences

- Source Serif 4: SIL Open Font License 1.1, in `static/fonts/OFL-source-serif-4.txt`. The files are Google Fonts' latin and latin-ext subsets, self-hosted with `font-display: swap`.
- Cabinet Grotesk: ITF Free Font License (FFL) 2.0, https://www.fontshare.com/licenses. The two weights the site uses, 400 and 800, load through Fontshare's own CSS API (`https://api.fontshare.com/v2/css?f[]=cabinet-grotesk@400,800&display=swap`, with preconnects to `api.fontshare.com` and `cdn.fontshare.com`), the route the licence itself provides. The repository holds no Cabinet Grotesk files, because the licence forbids modifying the fonts (subsetting included) and restricts redistributing them through repositories.
- Icons on member pages: Simple Icons (CC0 1.0) for ORCID, Google Scholar, ResearchGate, GitHub, Bluesky, X and LinkedIn, whose marks remain trademarks of their owners; Phosphor Icons (MIT) for the mail, website, CV, Dialnet and USAL portal glyphs.
- Member photos come from the members and from their institutional pages.
