# Messenger Chat

Messenger Chat is now configured for **Vercel + Supabase**.

## 1. Set up Supabase

1. Create a Supabase project.
2. In Supabase SQL Editor, run:
   - `supabase/schema.sql`
3. In Supabase Auth:
   - Enable Email sign-in.
   - (Optional) disable email confirmation for faster testing.
4. Copy:
   - Project URL
   - Anon public key

## 2. Add Supabase keys in this repo

Edit `static/config.js`:

```js
window.MESSENGER_CONFIG = {
  supabaseUrl: "https://YOUR_PROJECT_ID.supabase.co",
  supabaseAnonKey: "YOUR_SUPABASE_ANON_KEY"
};
```

Commit and push.

## 3. Deploy on Vercel

Deploy this repo on Vercel normally.

- Root path serves `index.html`
- App UI is `/static/index.html`
- Vercel config is static-only (`vercel.json`)

## Local preview

You can still run the old local Python server:

```bash
pip install -r requirements.txt
python server.py
```

For Vercel behavior, use static hosting and Supabase config.
