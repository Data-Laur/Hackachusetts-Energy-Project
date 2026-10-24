# Security & Secrets

## API keys and secrets

- **Never hardcode** API keys, tokens, or other secrets anywhere in the code,
  including Python scripts, JavaScript, HTML, and comments.
- **Never commit** secrets to GitHub.
- Load secrets **only** from:
  - a local **`.env`** file (for running on your own computer), or
  - **Vercel environment variables** (for the deployed serverless function).
- `.env` is already listed in `.gitignore` — keep it that way.
- The Streamlit secrets file (`.streamlit/secrets.toml`) is also gitignored if used.

### How to read a secret

Python (local):
```python
import os
api_key = os.environ["MY_API_KEY"]  # comes from .env or the environment
```

Serverless function (Vercel):
```javascript
const apiKey = process.env.MY_API_KEY; // set in Vercel project settings
```

## Keep the key on the server

- The AI provider key lives only in the **serverless function**, never in the
  frontend. The browser talks to our function; our function talks to the AI.
- Do not log secret values. Refer to them by name, not value.

## Sharing setup instructions

- When documenting setup, use placeholder names like `MY_API_KEY=your-key-here`
  in an example file (e.g. `.env.example`) rather than real values.
