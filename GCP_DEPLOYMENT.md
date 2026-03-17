# GCP Cloud Deployment Guide

## Quick Start

### Prerequisites
1. [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed
2. Docker Desktop running
3. GCP Billing account linked

### Deploy in 3 Steps

```bash
# 1. Login to GCP
gcloud auth login

# 2. First-time setup (creates project, APIs, registry)
./deploy.sh setup

# 3. Build and deploy
./deploy.sh deploy
```

---

## Secret Manager Setup

After running `./deploy.sh setup`, create your secrets:

```bash
# Google AI API Key
echo -n "AIza..." | gcloud secrets create GOOGLE_API_KEY --data-file=-

# Hyperliquid Wallet
echo -n "0x..." | gcloud secrets create HL_WALLET_ADDRESS --data-file=-
echo -n "your-private-key" | gcloud secrets create HL_PRIVATE_KEY --data-file=-

# Supabase
echo -n "https://xxx.supabase.co" | gcloud secrets create SUPABASE_URL --data-file=-
echo -n "eyJ..." | gcloud secrets create SUPABASE_KEY --data-file=-

echo -n "123456789" | gcloud secrets create TELEGRAM_CHAT_ID --data-file=-
```

---

## Management Commands

| Command | Description |
|---------|-------------|
| `./deploy.sh deploy` | Build & deploy (or update) |
| `./deploy.sh logs` | View recent logs |
| `./deploy.sh status` | Check VM status |
| `./deploy.sh stop` | Stop VM (save costs) |
| `./deploy.sh start` | Start VM |

---

## Viewing Logs in GCP Console

1. Go to [Cloud Logging](https://console.cloud.google.com/logs)
2. Use these filters:
   - **All logs:** `resource.type="gce_instance"`
   - **Council Debates:** `textPayload:"Council"`
   - **CPO Insights:** `textPayload:"CPO"`
   - **Trades:** `textPayload:"Trade"`
   - **Errors:** `severity>=ERROR`

---

## Cost Breakdown

| Resource | Monthly Cost |
|----------|--------------|
| e2-small VM (730h) | ~$13 |
| Artifact Registry | ~$0.10 |
| Secret Manager (8 secrets) | ~$0.06 |
| Cloud Logging (50GB free) | $0 |
| **Total** | **~$14/month** |

---

## SSH Access

```bash
gcloud compute ssh agent-trader-vm --zone=europe-west1-b
```

Once connected:
```bash
# View container logs
docker logs -f $(docker ps -q)

# Restart container
docker restart $(docker ps -q)
```

---

## Updating the Bot

After making code changes:

```bash
./deploy.sh deploy
```

This will:
1. Rebuild the Docker image
2. Push to Artifact Registry
3. Update the running container on the VM

---

## Troubleshooting

### Bot not starting?
```bash
# Check VM logs
./deploy.sh logs

# SSH and check container
gcloud compute ssh agent-trader-vm --zone=europe-west1-b
docker logs $(docker ps -aq | head -1)
```

### Secrets not loading?
```bash
# Verify secret exists
gcloud secrets versions access latest --secret=GOOGLE_API_KEY

# Check VM service account permissions
gcloud projects get-iam-policy YOUR_PROJECT_ID
```

### Rate limits?
The bot automatically waits 60 seconds on rate limit errors (implemented in `main.py`).
