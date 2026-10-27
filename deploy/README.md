# Deployment starter

From `deploy/`, run `docker compose up --build` for a local HTTP smoke test at `http://localhost/`. This is an API-only Compose starter; it does not deploy the React frontend or the model. `state/` stores SQLite data and should not be committed. Before exposing it publicly, configure a hostname, HTTPS, CORS, service health checks and secrets for the chosen environment. The final backend must run one worker while state is in memory.
