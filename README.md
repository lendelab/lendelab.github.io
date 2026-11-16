# LendeLab website

Source of https://lendelab.github.io, the website of LendeLab (Lenguaje en neurodegeneración), Universidad de Salamanca. The site is built with Hugo 0.170.0 and published with GitHub Pages. Spanish pages are at the root and English pages under `/en/`.

## Local preview

```
hugo server
```

opens a preview at http://localhost:1313/. `hugo --minify` builds the site into `public/`.

The layout check loads every page at widths from 320 to 1440 px in Chromium, Firefox and WebKit:

```
python -m pip install playwright==1.62.0
python -m playwright install chromium firefox webkit
python tests/check.py public
```

A second argument limits it to one browser, for example `python tests/check.py public firefox`.

## Editing content

Group members edit the site through Pages CMS (https://app.pagescms.org). The editing forms are defined in `.pages.yml`. Saving a change commits it to `main`, which rebuilds and republishes the site.

All content is YAML in `data/`. Texts have a Spanish and an English field (`_es` and `_en`); when the English field is empty, the English page shows the Spanish text.

| File or folder | Content |
|---|---|
| `data/site.yaml` | group description, home page, contact page, footer, settings |
| `data/members/` | one file per member |
| `data/lines/` | research lines |
| `data/projects/` | projects |
| `data/resources/` | corpora |
| `data/collaborations.yaml` | partner institutions |
| `data/outreach/` | one file per outreach activity, named by date |
| `data/theses.yaml` | theses supervised by members whose authors are outside the group |
| `data/publications/` | group publication list and works added by hand |
| `static/img/members/` | member photos |
| `i18n/` | interface labels |

Member and research line pages are generated from these files. The files in `content/` only hold section titles.

## Publications

Each member's works come from their ORCID record. A scheduled job (`.github/workflows/orcid.yml`, Mondays at 05:00 UTC) downloads them into `data/orcid/`; do not edit those files by hand. Mistakes are best corrected in ORCID itself. When that is not possible, a corrected copy with the same `id` in `data/publications/extra/<member>.yaml` replaces the ORCID version on the site. Works missing from ORCID go in the same file.

The publications page shows the curated list in `data/publications/group.yaml`. Each week the job opens a pull request on the branch `propuestas-publicaciones` with members' new works; merging it adds them to the list. To keep a work off the list:

```
python scripts/orcid_candidates.py reject ID --reason "..."
```

The job reads ORCID with a read-public token stored in the repository secret `ORCID_TOKEN`. `keepalive.yml` re-enables the scheduled jobs once a month, since GitHub disables them in repositories without recent activity.

## Deployment

Every push to `main` runs `.github/workflows/deploy.yml`: it builds the site, runs the layout check and publishes to GitHub Pages. The «Última actualización» date on each member page is the date of the last commit that changed that member's files.

## Settings

- Palette: `palette = "sage"` under `[params]` in `hugo.toml` switches to the sage colours. The default is `"teal"`.
- Visitor counter: put the GoatCounter site code in `goatcounter` in `data/site.yaml`. With the field empty, no counter is loaded.
- Contact form: messages go to a Google Form, whose address (`form_action`) and field ids (`entries`) are in `data/site.yaml`. Without them the contact page shows only the email address.

## Fonts, icons and photos

- Source Serif 4, SIL Open Font License 1.1, self-hosted in `static/fonts/`.
- Cabinet Grotesk, ITF Free Font License 2.0, loaded from Fontshare (`api.fontshare.com`, `cdn.fontshare.com`), as the licence does not allow the font files in a public repository.
- Profile icons from Simple Icons (CC0 1.0) and Phosphor Icons (MIT).
- Member photos come from the members themselves or from their institutional pages.
