# Transcription Console (frontend)

A Tufte-styled demo console for the transcription service: submit chunk
selections, watch a job fan out and stitch live, read the de-identified
transcript with mask highlighting, and page through the archive.

## Running

The compose stack serves the built console at http://localhost:5173
(nginx proxies `/transcribe` and `/transcript` to the API):

```sh
docker compose up --build -d
```

For local development against the same stack (Node 22, see `.nvmrc`):

```sh
npm install
npm run dev        # Vite on :5173 with the same two proxy roots
```

## API client

`src/api/schema.d.ts` is generated from the FastAPI OpenAPI schema and
committed. To regenerate after a backend contract change:

```sh
(cd ../backend && .venv/bin/python -c "import json; from app.main import create_app; print(json.dumps(create_app().openapi()))") > openapi.json
npm run codegen
```

## Tests

```sh
npm run test       # vitest unit tests (mask-token parsing)
npx tsc -b         # typecheck
npm run e2e        # Playwright smoke against the running compose stack
```

The smoke test submits three healthy chunks plus the always-failing one,
waits for `COMPLETED_WITH_ERRORS`, and asserts the de-identified mask chips
and the `[chunk N unavailable]` gap marker render.
