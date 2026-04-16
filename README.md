# Messager

Real-time messaging app with:
- account register/login
- direct messages
- group chats
- persisted chat history (SQLite)
- installable app (PWA) with logo

## Run locally

```bash
pip install -r requirements.txt
python server.py
```

Open `http://localhost:8080`.

On supported browsers, click **Install App** on the login screen to install it like an app.

## Deploy free (Koyeb)

1. Go to `https://app.koyeb.com` and sign in with GitHub.
2. Click **Create Web Service**.
3. Choose repo: `cburdick28-spec/Messager`.
4. Select **Dockerfile** deploy method.
5. Port: `8080` (or leave default from Dockerfile).
6. Deploy and share the generated public URL.

The app uses `PORT` automatically, so it works on hosted platforms.

## Always-on free VPS (Oracle Always Free)

1. Create an **Oracle Cloud Always Free** Ubuntu VM.
2. SSH into it.
3. Run:

```bash
git clone https://github.com/cburdick28-spec/Messager.git
cd Messager
chmod +x deploy/oracle_setup.sh deploy/update.sh
./deploy/oracle_setup.sh
```

4. Open inbound port `8080` in Oracle networking if needed.
5. Open app: `http://<YOUR_VM_PUBLIC_IP>:8080`

To update after new pushes:

```bash
cd /opt/messager
./deploy/update.sh
```
