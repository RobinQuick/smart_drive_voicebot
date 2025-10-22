Smart Drive Voice Bot — Deployment

This repo now includes a ready-to-use Netlify setup to host the frontend and proxy API calls to your Python backend.

Netlify (recommended quick path)
- What it does:
  - Serves the static frontend from `frontend/`.
  - Proxies browser calls from `/api/*` to your backend via a Netlify Function.

Steps
1) Deploy to Netlify (new site from this repo). Netlify will detect `netlify.toml` and publish `frontend/`.
2) Set an environment variable in Netlify: `BACKEND_ORIGIN` to your backend URL (e.g., `https://your-fastapi.example.com`).
   - The proxy function forwards methods, headers, body, and streams responses.
3) Open the site. The app calls `/api/token`, `/api/nlu`, `/api/pos/order` via the proxy.
4) Optional: in the UI, you can override the backend URL (input field). Leaving it blank uses `/api`.

Local dev
- Option A: Run your FastAPI backend locally (e.g., `uvicorn backend.app:app --port 8787`), then run `netlify dev` so the function proxy can forward `/api/*` to the backend. Set `BACKEND_ORIGIN=http://127.0.0.1:8787` in your Netlify dev env.
- Option B: Without Netlify dev, set the UI backend URL to `http://127.0.0.1:8787` (the app stores it in `localStorage`).

Amplify (alternative)
- If you prefer AWS Amplify Hosting, you can host `frontend/` and configure a Rewrite/Redirect rule to proxy `/api/*` to your backend URL.
- If you want to run the Python API on AWS (Lambda + API Gateway), I can add a small adapter (Mangum) and infra scaffold. Say the word and I’ll wire it up.

Notes
- Backend CORS: when using the Netlify proxy, browser CORS does not apply to your backend because calls are server-to-server. If calling the backend directly from the browser, ensure its CORS allows your site.
- Required env for backend: `OPENAI_API_KEY` (and any others in `backend/.env.example`).
