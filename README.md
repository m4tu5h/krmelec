# krmelec

A simple app project for daily lunch menus near the user in Bratislava. We are building it step by step and documenting the experiments.

The current milestone is a Jupyter notebook that searches restaurant websites for today's meals and saves structured JSON. Restaurants: Spilka, Centrálna Klubovňa and ALDA.

## Setup with uv

```sh
uv venv --python 3.9
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in your local `.env`; do not paste the key into notebook cells. `.env` is ignored by Git. If `.env` already exists, keep it instead of copying over it.

Open `notebooks/01_menu_agent.ipynb` in VS Code and select the project's `.venv` as the Python kernel. If VS Code reports that `ipykernel` is missing:

```sh
uv pip install --python .venv/bin/python ipykernel
```

## Run

Run the notebook sections in order: API-key setup, restaurant list, result models, search, save.

The active notebook uses `gpt-5.5` with `web_search`, restaurant-domain filters and today's date in `Europe/Bratislava`. It does not use the earlier prototype's `OPENAI_MODEL` setting.

The search cell makes paid API requests. The final save cell writes `menus.json` at the project root, replacing the previous file. Saving makes no API calls. If results are already in memory, run only the save cell to persist them. Restarting the kernel loses in-memory results but leaves the saved JSON intact.

## Data

`menus.json` contains `requested_date`, `saved_at` and a flat `meals` list. Each meal stores its name, restaurant, address, numeric EUR price or null, portion, source URL, Slovak labels, and possible soups with their additional prices. Soup surcharge `0` means explicitly included, `null` means unknown, and `[]` means no confirmed soup options.

Labels: `cestoviny`, `bravčové`, `hovädzie`, `hydina`, `šalát`, `ryby`, `syr`, `zelenina`.

Review the sources before relying on dates, prices, soup pairings and labels. Structured Outputs enforce the shape, not factual accuracy. Restaurants whose dates cannot be verified contribute no meals. The file currently has no separate status for those restaurants.

## Project files

- `notebooks/01_menu_agent.ipynb`: active learning and extraction workflow.
- `menus.json`: latest saved meals for the future app.
- `data/raw-menu-results.json`: original Markdown answers preserved during migration.
- `docs/build-log.md`: experiment history, decisions, validation and limitations.
- `menu_agent.py`, `restaurants.json`, `tests/`: earlier standalone prototype, not used by the notebook. Its tests do not validate the current live-search workflow.

No web app, scheduled collection or history is implemented yet.

References: [web search](https://developers.openai.com/api/docs/guides/tools-web-search), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
