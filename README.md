# Development bank and international organisation vacancies

Collects job postings from the public feeds that multilateral development banks
and international organisations already publish, puts them in one list, and
refreshes it every morning. Once a week it drafts a newsletter of what's new.

No web scraping. Every source is an API the organisation publishes on purpose.

---

## How the whole thing works

Nothing here needs a server, a database, or a paid account.

```
  config/sources.yaml     you list which job feeds to read
           │
           ▼
  scripts/fetch.py        reads each feed, tidies the results, merges them
           │              with what it already knew
           ▼
  data/jobs.json          the dataset — committed to git, so every past
           │              version is kept automatically
           ├──────────────► docs/index.html   one long table, grouped by
           │                                  organisation. Just scroll.
           │                docs/jobs.csv     the same thing, opens in Excel
           ▼
  scripts/digest.py       writes digests/YYYY-MM-DD.md — your Substack draft
```

Two automations, deliberately separate:

```
  .github/workflows/daily.yml           05:30 UTC every day  — collect
  .github/workflows/weekly-digest.yml   07:00 UTC Mondays    — draft newsletter
```

They're separate files so they can fail independently. If the newsletter step
breaks, the list still keeps updating.

**ReliefWeb** (run by UN OCHA) is the big one: it already aggregates postings
from most UN agencies and many development banks behind a single free API. That
one source does most of the work on day one.

The rest is a second useful fact: most institutions rent their careers page from
a handful of vendors — SmartRecruiters, Greenhouse, Workday, Oracle — and each
vendor serves all of its clients from one API where only a company name changes.
So you don't write forty collectors. You write one per vendor and add
organisations as config lines.

### Why daily collection but weekly sharing

Postings appear and close on no fixed schedule, and some have short windows. If
you collected weekly you'd miss vacancies that opened and closed in between.

Collecting daily costs nothing extra and gives you an accurate
`first_seen` date for every posting, which is exactly what the weekly newsletter
needs to say "here's what appeared this week". Collection frequency and
publishing frequency are separate decisions, and they should be.

### Why the data lives in a git file and not a database

Git already is a database for this purpose. It stores every version, it tells
you precisely what changed each day, it costs nothing, it needs no maintenance,
and you can open the data in any text editor. A real database is the right call
at a few hundred thousand records. You'll have a few thousand.

---

## Setup, step by step

You need Python 3.10 or newer and a GitHub account. About 30 minutes.

### 1. Run it on your own machine

```bash
# An isolated space for this project's libraries, so installing something
# here can never break another project on your computer.
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

python scripts/fetch.py
```

You'll see one line per source with a count. If ReliefWeb returns zero, open
<https://apidoc.reliefweb.int/> and check whether the address or required
parameters have changed, then fix `scripts/collectors/reliefweb.py`.

### 2. Look at the list

```bash
python -m http.server 8000 --directory docs
```

Open <http://localhost:8000>.

Double-clicking `docs/index.html` will **not** work — browsers block local files
from loading other local files. Use the command above.

### 3. Put it on GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/mdb-jobs.git
git push -u origin main
```

### 4. Turn on the automation

On github.com, in your repository:

- **Settings → Actions → General → Workflow permissions** → choose
  *Read and write permissions* and save. Without this the daily run can't
  commit its results, and it will fail every morning.
- **Actions** tab → *Daily collection* → **Run workflow**. Test it now rather
  than waiting until tomorrow. If it fails, the log names the source that broke.

### 5. Publish the page

**Settings → Pages** → Source: *Deploy from a branch*, Branch `main`,
Folder `/docs`. A few minutes later it's live at
`https://YOUR-USERNAME.github.io/mdb-jobs/`.

Then search the project for `YOUR-USERNAME` and replace it — it appears in
`scripts/digest.py` and `scripts/collectors/base.py`.

### 6. The newsletter

Every Monday the workflow commits a file in `digests/`. Open it, write the two
or three sentences at the top that only you can write, paste it into Substack,
publish.

Substack has no reliable public API for creating posts. Tools claiming otherwise
drive a logged-in browser session and can get your account flagged. The manual
paste takes five minutes, and it's also the part that makes the newsletter worth
subscribing to — an automated dump of eighty links is a feed, not a publication.

---

## The page

One table. No filters, no dropdowns, no search. Grouped by organisation
alphabetically, and within each organisation sorted by whichever closes soonest.
The links across the top jump to an organisation; they don't filter, so nothing
ever disappears on you.

- Column headers and organisation banners stay put as you scroll.
- Postings whose deadline has passed are hidden from the page but kept in
  `data/jobs.json`, so the history stays intact.
- **New** marks a posting that arrived in the last 7 days.
- **Download as CSV** gives you the whole thing in Excel.

If you later want to sort by clicking a column, or filter by seniority, both are
small additions — but use it as it is for a few weeks first. You'll find out
whether you actually want them, and roughly 60% of the time the answer is no.

---

## Adding an organisation

First find its feed. Open the careers page, press **F12**, go to the **Network**
tab, filter to **Fetch/XHR**, reload the page. The requests listed there are the
feed the page itself is reading. Paste one into your browser: if you get JSON,
you've found it, and you're done in ten minutes.

| What you found | What to do |
|---|---|
| It's already on ReliefWeb | Add its exact ReliefWeb source name to the `organisations` list in `config/sources.yaml`. That's all. |
| `jobs.smartrecruiters.com/SLUG/...` | Add `{slug: SLUG, organisation: "..."}` under the SmartRecruiters entry, set `enabled: true`. |
| `boards.greenhouse.io/SLUG` | Same, under the Greenhouse entry. |
| A different JSON feed | Copy `scripts/collectors/ats.py` as a model, write a new collector class, register it in `scripts/collectors/__init__.py`. |
| No feed at all | Email them and ask. International organisations are often glad someone's surfacing their vacancies. If the answer is no, leave that organisation out. |

Add **one source at a time** and run `python scripts/fetch.py` after each. Add
six at once and a failure tells you nothing about which one caused it.

To check what ReliefWeb calls an organisation, open
<https://reliefweb.int/jobs> and read the Organization filter. The name in your
config has to match it exactly.

---

## Things that will go wrong

**A feed goes quiet without saying so.** An address changes, and `fetch.py`
cheerfully reports zero jobs for that source. It prints a per-source count for
exactly this reason — glance at the Actions log now and then. If one source
matters a lot to you, make the run fail when it returns zero.

**Duplicates across sources.** A World Bank vacancy can appear on both ReliefWeb
and the Bank's own feed under different ids, so it shows twice. Fixing this
means fuzzy-matching titles within an organisation. Don't build it until you can
see from your own data how often it actually happens.

**Deadlines move.** Some organisations extend a closing date without updating
the feed. The footer of the page tells readers to check the original posting.
Keep that there.

**Seniority is guessed, not given.** `scripts/normalise.py` maps grade codes
(World Bank GA–GK, UN P-1 to D-2) onto six levels using rules. It gets the
common cases right and flags the rest as `unclassified`. Nothing in the current
page depends on it, but the newsletter groups by it, so check it occasionally.

---

## Project layout

```
config/sources.yaml              which feeds to read — usually the only file
                                 you need to edit
scripts/
  fetch.py                       the conductor: run this
  normalise.py                   seniority levels, location tidying
  digest.py                      writes the weekly Substack draft
  collectors/
    base.py                      the shared shape every source produces
    reliefweb.py                 UN system and IFIs, one free API
    ats.py                       SmartRecruiters and Greenhouse
data/jobs.json                   the dataset, including closed postings
data/jobs.csv                    the same thing for Excel
docs/index.html                  the table
docs/data.json, docs/jobs.csv    copies the published page can reach
docs/DESIGN.md                   why the page looks the way it does
digests/                         weekly newsletter drafts
.github/workflows/               the daily and weekly automation
```

## Suggested order of work

1. Get `fetch.py` returning ReliefWeb vacancies on your machine.
2. Get the table loading them locally.
3. Push to GitHub, turn on Actions and Pages.
4. Let it run for two or three weeks. Read what comes in.
5. *Then* add more sources — by then you'll know which ones you're missing.
6. Start the newsletter once you have a few weeks of history to write about.

Resist step 5 until step 4 has actually happened. The usual way a project like
this dies is adding twenty sources in week one and spending every week after
that repairing them.
