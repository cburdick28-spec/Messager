# Messager

Real-time messaging app with:
- account register/login
- direct messages
- group chats
- persisted chat history (SQLite)

## Run locally

```bash
pip install -r requirements.txt
python server.py
```

Open `http://localhost:8080`.

## Deploy free (Koyeb)

1. Go to `https://app.koyeb.com` and sign in with GitHub.
2. Click **Create Web Service**.
3. Choose repo: `cburdick28-spec/Messager`.
4. Select **Dockerfile** deploy method.
5. Port: `8080` (or leave default from Dockerfile).
6. Deploy and share the generated public URL.

The app uses `PORT` automatically, so it works on hosted platforms.
