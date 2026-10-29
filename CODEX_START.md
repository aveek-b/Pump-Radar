# PumpRadar integration status

The repository has one project root with `api/`, `web/`, `src/`, `models/`, and `results/`. Read `README.md` for current setup and commands.

The integration branch includes current `origin/main` through `c13d187` and Hannah's `feat/feature-engineering`. The frozen Experiment B linear SVM uses the 28 ordered columns in `models/features_B.json` and the feature implementation in `src/pumpradar/features.py`. Hannah's newer feature builder is retained separately as `features_v2.py` and `build_xsec.py`; its columns are incompatible with the frozen model and must not be substituted silently.

The React Radar can show raw 10-minute SVM ranking margins from real BTC-pair minute bars after operator-triggered backfill and live feeder ingestion. The mock dashboard and five-bar heuristic remain clearly separate. The provisional threshold has no validated live false-alert rate. Historical Experiments A and B are reported separately from live deployment metrics. Price-only historical replay has no model alert frames.

Remaining work needs measured live alert precision, recall, false-alert budget and warning lead, an evaluated replay, deployment, and team paper/demo contributions. Do not turn historical AP or a raw margin into a probability claim. After API changes, regenerate `api/openapi.json` and `web/src/api/types.ts`; run Python tests, Ruff, the web build and browser checks.
