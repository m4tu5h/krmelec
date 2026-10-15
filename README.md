# krmelec

A simple app project for daily lunch menus near the user in Bratislava. We are building it step by step and documenting the experiments.

The working flow searches restaurant websites for today's meals, saves structured JSON and displays it in a mobile-friendly web app. Restaurants: Spilka, Centrálna Klubovňa, ALDA and Cafe & Restaurant Michaela.

## Setup with uv

```sh
uv venv --python 3.9
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
```

Set `TAVILY_API_KEY` and `OPENAI_API_KEY` in local `.env`. `OPENAI_MODEL` optionally selects the extraction model (default `gpt-4.1-mini`). Keep keys out of notebook cells; `.env` is ignored by Git. Keep an existing `.env` rather than copying over it.

Open `notebooks/01_menu_agent.ipynb` in VS Code and select the project's `.venv` as the Python kernel. If VS Code reports that `ipykernel` is missing:

```sh
uv pip install --python .venv/bin/python ipykernel
```

## Manual collection from the terminal

From the project folder:

```sh
uv run python collect_menus.py
```

This runs Tavily search → actual HTML/PDF downloads → OpenAI extraction and validation → atomic save to `menus.json`. It uses today's date in Bratislava and the keys/model from `.env`. Refresh the web app after a successful save. The server does not need to run during collection.

The command skips API calls if today's saved menu already contains all configured restaurants. To intentionally collect again (with API costs), use `uv run python collect_menus.py --force`; this repeats discovery and all extraction. A failed batch exits with status 1 and leaves the app's existing menus unchanged. Diagnostic responses and checkpoints remain under `data/diagnostics/` for notebook review/recovery. Overlapping terminal-command runs are blocked by a local file lock; this does not lock notebook execution, so avoid running both at once.

Check configuration without API calls or menu writes:

```sh
uv run python collect_menus.py --check
```

`restaurants.json` is now the shared restaurant configuration for this command and the active notebook. It contains names, addresses, official domains, stable menu pages and the approved yearless-date policy. No automatic schedule is installed; collection remains manual.

## Run the notebook

Run `notebooks/01_menu_agent.ipynb` in order:

1. Load both API keys and helpers.
2. Select restaurants, stable menu pages and today's date.
3. Discover links with Tavily basic Search.
4. Fetch actual HTML/PDF menu contents with Python.
5. Extract structured meals with OpenAI, then validate source evidence.
6. Save verified meals to `menus.json`.

The notebook is a step-by-step interface to reusable functions in `menu_pipeline.py`:

- `search_restaurants(...)`: discover links using Tavily.
- `retrieve_restaurants(...)`: download actual HTML/PDF contents.
- `extract_menus(...)`: extract, validate and checkpoint responses.
- `recover_extraction(...)`: recover the last checkpoint without API calls.

Notebook section 2 loads the shared `restaurants.json` configuration. After helper changes, reload the notebook and run setup to reload the Python modules. Setup itself makes no paid requests.

Extraction reuses verified results when the date, restaurant configuration and prepared source text match. Only failed, missing or changed restaurants trigger requests. To intentionally compare another model on all sources, set `retry_failed_only=False` in section 5. Changing the model alone does not bypass reuse.

The main path does not use Tavily Research or OpenAI web search. Each selected restaurant gets one Tavily basic-search request. The retrieval cell makes ordinary HTTP downloads without AI calls. Extraction uses paid OpenAI tokens and can be rerun on the same retrieved text without more searches/downloads. All dates use `Europe/Bratislava`.

Python first opens stable menu pages, follows likely daily-menu/PDF links (up to two levels), and reads actual PDF text. It never substitutes stale Tavily snippets for retrieved contents. Downloads are bounded to eight per restaurant and 8 MB each; source text is bounded to 45,000 characters per source with truncation reported. Sources and errors remain inspectable in `retrieved_results`. Image-only/scanned PDFs, JavaScript-rendered menus and blocked pages may still fail; no vision/browser fallback is implemented.

Before extraction, Python narrows recognised menus to the requested weekday/date and restricts Centrálna Klubovňa PDFs to the CK branch. The extraction model must quote date/day/price evidence from supplied sources. Soup `price_evidence` can separately quote a global with-menu pricing rule; it is not exported into the app JSON. The shared checks in `tavily_agent.py` validate those quotes, full calendar dates and soup inclusion. By user choice, `allow_yearless_dates` is enabled in the notebook: a heading without a year may use the current year only when day, month and Slovak weekday match. Those meals carry `date_assumed: true` and a `date_note`, displayed in the app detail. Copyright-year text is not treated as menu-date proof. Conflicting/unverifiable dates, empty results or failed checks block saving the selected batch. These checks are conservative and do not establish completeness or every pairing/ingredient. Compare the results with the originals, especially when changing models. `OPENAI_MODEL` is configurable so extraction models can be compared against the same retrieved input.

By default all four restaurants are selected. Use `selected_restaurants = restaurants[:1]` for an initial Spilka test. Saving replaces the app's menu with only the selected list, so select all restaurants before saving the full app menu.

The save cell atomically replaces `menus.json` and makes no API requests. Failed batches leave the existing file untouched. The successful October 13 run saved 22 meals across the four restaurants. This snapshot does not automatically refresh each day.

Each paid response is checkpointed before validation to ignored `data/diagnostics/pending-extraction.json`; the latest batch is recorded in `data/diagnostics/latest-run.json`. If local processing fails after a response returns, use the optional recovery cell instead of repeating extraction. Recovery reads disk, so the response survives a kernel restart. Run setup first after a restart. If the batch contains unprocessed restaurants, resume section 5 afterward. The optional recheck cell applies current validation to the latest saved batch without any API calls. Both cells update `menu_results` for review; neither writes `menus.json`.

## Data

`menus.json` contains `requested_date`, `saved_at` and a flat `meals` list. Each meal stores its name, restaurant, address, numeric EUR price or null, portion, source URL, Slovak labels, and possible soups with their additional prices. When the menu year is assumed under the explicit policy, `date_assumed` and `date_note` flag that assumption. Soup surcharge `0` means explicitly included, `null` means unknown, and `[]` means no confirmed soup options.

Labels: `cestoviny`, `bravčové`, `hovädzie`, `hydina`, `šalát`, `ryby`, `syr`, `zelenina`.

Review the sources before relying on dates, prices, soup pairings and labels. Structured Outputs enforce the shape, not factual accuracy. Restaurants whose sources/dates cannot be verified block saving the selected batch. Status and diagnostics live in the local task records; the app JSON retains its existing schema.

## Project files

- `notebooks/01_menu_agent.ipynb`: active Tavily Search → retrieval → OpenAI workflow.
- `build_site.py`: packages only public app files and saved menus into `dist/site/`.
- `collect_menus.py`: manual terminal collection, configuration check and overlapping-command protection.
- `restaurants.json`: shared restaurant configuration for the active notebook and terminal command.
- `menu_pipeline.py`: reusable search, retrieval, extraction and disk-based recovery functions; importing it makes no API requests.
- `menu_retrieval.py`: bounded HTML/PDF fetching and menu-link traversal.
- `tavily_agent.py`: shared evidence models, date/price checks and saving; its Research API class is retained for the archived experiment only.
- `notebooks/02_tavily_search.ipynb`: isolated one-restaurant search inspection.
- `notebooks/03_openai_web_search_backup.ipynb`: previous OpenAI hosted-search workflow.
- `notebooks/04_tavily_search_gpt_backup.ipynb`: original basic-search/GPT experiment with failed-run diagnostics.
- `notebooks/05_tavily_research_backup.ipynb`: archived Tavily-only Research experiment.
- `menus.json`: latest saved meals for the future app.
- `data/raw-menu-results.json`: original Markdown answers preserved during migration.
- `docs/build-log.md`: experiment history, decisions, validation and limitations.
- `menu_agent.py`: earlier standalone prototype, not used by the current workflow; its old SME configuration has been replaced in `restaurants.json`. Its original tests do not validate the current live-search workflow; `tests/test_tavily_notebook.py` checks shared validation and archived Research behaviour; `tests/test_collect_menus.py` checks command saves, failed-batch preservation, configuration and overlapping runs; `tests/test_menu_pipeline.py` checks failed-only retries, reuse, checkpoints and recovery with mocked APIs; `tests/test_menu_retrieval.py` exercises the active retrieval stage with fake HTTP responses and a generated PDF.

## Prepare the static app for publishing

```sh
uv run python build_site.py
```

This creates `dist/site/` containing exactly `index.html`, `style.css`, `app.js` and the current `menus.json`. These files can be uploaded as one static site; `/menus.json` is available at the path the app expects. The packaging command does not publish anything or call any APIs.

Only those four explicitly named files are copied. `.env`, notebook outputs, Python scripts and diagnostics are excluded. The dedicated `dist/site/` directory is rebuilt from scratch to remove stale files. `dist/` is already ignored by Git. The source files are unchanged.

Rebuild after updating the menus or app. A hosted copy will not automatically reflect changes to the local `menus.json`. For Cloudflare Pages, use `uv run python build_site.py` as the build command and `dist/site` as the build output directory if deploying from Git, or upload the contents of `dist/site` for a manual deployment. Cloudflare deployment is not configured yet.

## Local web app

From the project root, run:

```sh
uv run python serve.py
```

Open http://127.0.0.1:8000. Stop the server with Ctrl+C. The server exposes the `web/` folder and root `menus.json`, rather than serving the whole project. No extra packages or build step are needed.

The mobile-first Slovak interface reuses the supplied design: compact alternating meal rows, Krmelec wordmark, expandable in-flow filters and a meal-detail dialog with restaurant, portion, labels, soup surcharges and a source link. The browser loads real data from root `menus.json`; no sample meals are bundled.

Filtering specification:

- No selections in a group means all values in that group.
- Selected restaurants use OR: a meal can belong to any selected restaurant.
- Selected labels use OR: a meal needs **any selected label**.
- Restaurant and label groups combine with AND.
- Filters apply immediately; clicking a selected chip again removes it.
- Reset clears both groups. Escape closes the filter panel or native detail dialog.

The supplied design has no maximum-price filter or soup-selection total calculator; soup prices are shown in the detail dialog. Unknown prices are displayed as unknown. The meal detail displays any date-year assumption. The footer and meal detail show the menu date; the footer indicates when the saved menu is not for today in Bratislava. Browsing never requests AI extraction.

After running the notebook's save cell, refresh the page to load updated menus. The app uses `fetch`, so open it through the server rather than double-clicking the HTML file. The server is local to this computer; mobile-friendly refers to the layout, not public hosting.

- `web/index.html`: page structure.
- `web/style.css`: supplied design, responsive layout and appearance.
- `web/app.js`: JSON loading, OR filters and meal-detail dialogs.
- `serve.py`: small local Python server.

Scheduled collection and history are not implemented yet.

References: [web search](https://developers.openai.com/api/docs/guides/tools-web-search), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Optional Tavily experiment

`notebooks/02_tavily_search.ipynb` tests one basic Tavily search for Spilka, separately from the working agent. Add `TAVILY_API_KEY` to local `.env`, then run its cells in order. It reuses existing dependencies and prints returned source links, content and reported credit usage. It does not call OpenAI or change `menus.json`. Search uses Tavily credits; the account's free allowance is finite. Menu extraction with another model is a later step after checking search quality.

## Offline notebook checks

```sh
.venv/bin/python -m unittest discover -s tests -p test_tavily_notebook.py
.venv/bin/python -m unittest discover -s tests -p test_menu_retrieval.py
```

These make no live requests. They verify menu-link/PDF retrieval, blocked/malformed sources, traversal limits, source/date/price evidence, the September/October regression, soup inclusion and app-compatible saving. They also retain tests for the archived Research helper. They do not prove live accuracy or that every menu item has been found. Each extraction now automatically saves all model responses, the prepared model inputs and original sources to ignored `data/diagnostics/latest-run.json` so failed fields can be inspected without another API call.
