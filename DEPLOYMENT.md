# Deployment Guide

Since you don't have Docker installed locally, you have two options:
1. **Install Docker** to build and test locally.
2. **Deploy directly to the web** (Cloud providers will handle the Docker build for you).

## Option 1: Install Docker Locally (Mac)

Since you have Homebrew installed, run:

```bash
brew install --cask docker
```

1. After installation, open **Docker** from your Applications folder.
2. Wait for the engine to start (whale icon in status bar stops animating).
3. Try the build command again:
   ```bash
   docker build -t bookcut .
   ```

## Option 2: Deploy to the Web

The `Dockerfile` we created makes your application ready for any container-based hosting platform.

### Recommended: Render.com (Easiest)
1. Push your code to a GitHub repository.
2. Sign up at [dashboard.render.com](https://dashboard.render.com).
3. Click **New +** -> **Web Service**.
4. Connect your GitHub repository.
5. Render will automatically detect the `Dockerfile`.
6. Click **Create Web Service**.
   - Render will build the Docker image in the cloud and host it.
   - You will get a URL like `https://bookcut.onrender.com`.

### Alternative: Fly.io (CLI based)
1. Install flyctl: `brew install flyctl`
2. Signup/Login: `fly auth signup`
3. Initialize (run in `BookCut` folder):
   ```bash
   fly launch
   ```
   - It will detect the Dockerfile.
   - Accept defaults.
4. Deploy: `fly deploy`

## Environment Variables
Remember to set environment variables in your cloud provider's dashboard:
- `BOOKCUT_DIR`: `/data` (Already set in Dockerfile, but good to know)
- `PORT`: `8000` (Render/Fly usually handle this automatically, but ensure mapped port is 8000).

## Persistence Note
The `path/to/downloaded/books` (mapped to `/data`) will be **ephemeral** on most free-tier hosting (files disappear on restart).
- To keep downloaded books permanently, you need to attach a **Persistent Volume/Disk** provided by your host (supported by Render Paid, Fly.io, etc.).
