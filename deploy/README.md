# Deployment Guide

## Files

- `nginx.conf` - Nginx reverse proxy configuration
- `lawncare.service` - Systemd service unit file
- `deploy.sh` - Automated deployment script

## Quick Start

### Prerequisites

- Ubuntu 22.04+ or Debian 12+ VPS
- Root SSH access
- Domain name pointing to server IP

### Full Deployment

```bash
# Upload files to server
scp -r . root@your-server:/tmp/lawn

# SSH to server
ssh root@your-server

# Run deployment
cd /tmp/lawn
chmod +x deploy/deploy.sh
./deploy/deploy.sh all
```

### Step-by-Step Deployment

```bash
# Install system packages
./deploy/deploy.sh system

# Setup PostgreSQL
./deploy/deploy.sh database

# Setup Redis
./deploy/deploy.sh redis

# Setup application
./deploy/deploy.sh app

# Run database migrations
./deploy/deploy.sh migrations

# Setup Nginx
./deploy/deploy.sh nginx

# Get SSL certificate
./deploy/deploy.sh ssl

# Setup systemd service
./deploy/deploy.sh service

# Configure firewall
./deploy/deploy.sh firewall
```

## Post-Deployment

### Configure Environment

Edit `/var/www/lawn/.env`:

```bash
SECRET_KEY=<generated-during-deploy>
DATABASE_URL=postgresql+asyncpg://lawnuser:password@localhost:5432/lawncare
REDIS_URL=redis://localhost:6379
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

### Stripe Webhook

Configure webhook in Stripe Dashboard:
- URL: `https://veteranlawnsandlandscapes.com/payments/webhook`
- Events: `checkout.session.completed`, `customer.subscription.deleted`

### Create Admin User

```bash
cd /var/www/lawn
source venv/bin/activate
python -c "
from auth import get_password_hash
print(get_password_hash('your-admin-password'))
"

# Then in psql:
sudo -u postgres psql lawncare
INSERT INTO users (email, hashed_password, role, is_active, email_verified)
VALUES ('admin@example.com', '<hashed-password>', 'admin', true, true);
```

## Maintenance

### View Logs

```bash
# Application logs
journalctl -u lawncare -f

# Nginx access logs
tail -f /var/log/nginx/lawncare_access.log

# Nginx error logs
tail -f /var/log/nginx/lawncare_error.log
```

### Restart Services

```bash
systemctl restart lawncare
systemctl restart nginx
systemctl restart redis
systemctl restart postgresql
```

### Update Application

```bash
cd /var/www/lawn
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
systemctl restart lawncare
```

### Database Backup

```bash
# Manual backup
sudo -u postgres pg_dump lawncare > backup_$(date +%Y%m%d).sql

# Setup daily cron
echo "0 2 * * * postgres pg_dump lawncare > /var/backups/lawncare_\$(date +\%Y\%m\%d).sql" | sudo tee /etc/cron.d/lawncare-backup
```

### SSL Certificate Renewal

Certbot handles automatic renewal. To test:

```bash
certbot renew --dry-run
```

## Troubleshooting

### Service Won't Start

```bash
# Check status
systemctl status lawncare

# Check logs
journalctl -u lawncare -n 50

# Test manually
cd /var/www/lawn
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000
```

### Database Connection Issues

```bash
# Check PostgreSQL is running
systemctl status postgresql

# Test connection
sudo -u postgres psql -c "SELECT 1;"

# Check database exists
sudo -u postgres psql -c "\l" | grep lawncare
```

### Redis Connection Issues

```bash
# Check Redis is running
systemctl status redis

# Test connection
redis-cli ping
```

### Nginx Issues

```bash
# Test configuration
nginx -t

# Check error logs
tail -f /var/log/nginx/error.log
```
