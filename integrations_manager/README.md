# GoalOS Integrations Manager

A secure, centralized dashboard for managing credentials for all GoalOS integrations.

## Features

- 🔐 **Encrypted credential storage** — AES-256-GCM at rest
- 🔑 **Admin authentication** — JWT tokens + CSRF protection
- 🔗 **OAuth 2.0 flows** — Google Analytics, Meta, LinkedIn, Reddit, X/Twitter
- 🛒 **API key management** — WooCommerce
- 🧪 **Connection testing** — verify each integration works
- 📊 **Status dashboard** — see all integrations at a glance
- 📝 **Audit logging** — track all credential operations
- 🚫 **Secrets never exposed** — masked values in UI, never returned by API

## Supported Integrations

| Integration | Auth Type | Capabilities |
|---|---|---|
| WooCommerce | API Key | Store URL, Consumer Key/Secret |
| Google Analytics 4 | OAuth 2.0 | Property discovery, analytics |
| Meta / Facebook | OAuth 2.0 | Pages, Instagram, insights |
| LinkedIn | OAuth 2.0 | Profile, publishing, analytics |
| X / Twitter | OAuth 2.0 | Tweets, metrics |
| Reddit | OAuth 2.0 | Posts, comments, karma |

## Quick Start

### 1. Generate encryption key

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set:
#   IM_ENCRYPTION_KEY=<your-generated-key>
#   IM_ADMIN_PASSWORD=<your-admin-password>
#   IM_JWT_SECRET=<random-secret>
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the server

```bash
uvicorn integrations_manager.app.main:app --host 0.0.0.0 --port 8001
```

### 5. Open the dashboard

Navigate to `http://localhost:8001` and log in with your admin credentials.

## API Endpoints

### Public

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check (no secrets) |

### Authentication

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/login` | Login, returns JWT + CSRF token |
| GET | `/api/auth/csrf` | Get fresh CSRF token |

### Integrations

| Method | Path | Description |
|---|---|---|
| GET | `/api/integrations` | List all integrations + status |
| GET | `/api/integrations/{slug}` | Get integration detail |
| GET | `/api/integrations/{slug}/credentials` | Get masked credentials |
| POST | `/api/integrations/{slug}/credentials` | Save credentials (encrypted) |
| POST | `/api/integrations/{slug}/test` | Test connection |
| POST | `/api/integrations/{slug}/connect` | Initiate OAuth / configure |
| POST | `/api/integrations/{slug}/disconnect` | Remove all stored credentials |
| GET | `/api/integrations/{slug}/status` | Get connection status |
| GET | `/api/integrations/{slug}/audit` | Get audit logs |

### OAuth Callbacks

| Method | Path | Description |
|---|---|---|
| GET | `/api/oauth/google/callback` | Google OAuth callback |
| GET | `/api/oauth/meta/callback` | Meta OAuth callback |
| GET | `/api/oauth/linkedin/callback` | LinkedIn OAuth callback |
| GET | `/api/oauth/reddit/callback` | Reddit OAuth callback |
| GET | `/api/oauth/twitter/callback` | X/Twitter OAuth callback |

## Security

- Credentials encrypted with AES-256-GCM at rest
- Master key from environment variable only
- JWT authentication with configurable expiry
- CSRF protection on state-changing requests
- Secrets never returned by any API endpoint
- Audit logging for all credential operations
- Rate limiting on login endpoint
- No secrets in logs or error messages

## Adding a New Integration

1. Create `integrations_manager/app/providers/your_provider.py`
2. Implement `BaseProvider` abstract class
3. Register in `integrations_manager/app/providers/__init__.py`
4. The system auto-discovers and seeds the integration

## Deployment

### Environment Variables (required)

```
IM_ENCRYPTION_KEY=<64-char-hex>
IM_ADMIN_PASSWORD=<secure-password>
IM_JWT_SECRET=<random-secret>
IM_DATABASE_URL=sqlite:///./integrations_manager.db
IM_OAUTH_REDIRECT_BASE=https://your-domain.com
```

### Production

```bash
pip install -r requirements.txt
uvicorn integrations_manager.app.main:app --host 0.0.0.0 --port 8001
```

### With systemd

```ini
[Unit]
Description=GoalOS Integrations Manager
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/GoalOS
ExecStart=/opt/GoalOS/.venv/bin/uvicorn integrations_manager.app.main:app --host 0.0.0.0 --port 8001
Restart=always
EnvironmentFile=/etc/goalos/integrations-manager.env

[Install]
WantedBy=multi-user.target
```
