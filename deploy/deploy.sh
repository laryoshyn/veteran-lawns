#!/bin/bash
# Deployment script for Veteran Lawns & Landscapes
# Run as root on the VPS

set -euo pipefail

# Configuration
APP_NAME="lawncare"
APP_DIR="/var/www/lawn"
LOG_DIR="/var/log/lawn"
DOMAIN="veteranlawnsandlandscapes.com"
DB_NAME="lawncare"
DB_USER="lawnuser"
PYTHON_VERSION="3.12"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

# =============================================================================
# Phase 1: System Setup
# =============================================================================
setup_system() {
    log_info "Updating system packages..."
    apt update && apt upgrade -y

    log_info "Installing required packages..."
    apt install -y \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-venv \
        python${PYTHON_VERSION}-dev \
        postgresql \
        postgresql-contrib \
        redis-server \
        nginx \
        certbot \
        python3-certbot-nginx \
        git \
        curl \
        build-essential \
        libpq-dev

    log_info "System packages installed"
}

# =============================================================================
# Phase 2: Database Setup
# =============================================================================
setup_database() {
    log_info "Setting up PostgreSQL..."

    # Start PostgreSQL if not running
    systemctl enable postgresql
    systemctl start postgresql

    # Create database and user
    sudo -u postgres psql -c "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}';" | grep -q 1 || {
        log_info "Creating database ${DB_NAME}..."
        sudo -u postgres createdb ${DB_NAME}
    }

    sudo -u postgres psql -c "SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}';" | grep -q 1 || {
        log_info "Creating database user ${DB_USER}..."
        read -sp "Enter password for database user ${DB_USER}: " DB_PASS
        echo
        sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';"
        sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"
        sudo -u postgres psql -c "ALTER DATABASE ${DB_NAME} OWNER TO ${DB_USER};"
    }

    log_info "PostgreSQL setup complete"
}

# =============================================================================
# Phase 3: Redis Setup
# =============================================================================
setup_redis() {
    log_info "Setting up Redis..."

    systemctl enable redis-server
    systemctl start redis-server

    # Test Redis connection
    redis-cli ping > /dev/null 2>&1 && log_info "Redis is running" || log_error "Redis failed to start"
}

# =============================================================================
# Phase 4: Application Setup
# =============================================================================
setup_application() {
    log_info "Setting up application..."

    # Create directories
    mkdir -p ${APP_DIR}
    mkdir -p ${LOG_DIR}

    # Clone or update repository
    if [[ -d "${APP_DIR}/.git" ]]; then
        log_info "Updating existing repository..."
        cd ${APP_DIR}
        git fetch origin
        git reset --hard origin/main
    else
        log_info "Cloning repository..."
        read -p "Enter git repository URL: " REPO_URL
        git clone ${REPO_URL} ${APP_DIR}
    fi

    cd ${APP_DIR}

    # Create virtual environment
    log_info "Creating Python virtual environment..."
    python${PYTHON_VERSION} -m venv venv
    source venv/bin/activate

    # Install dependencies
    log_info "Installing Python dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt

    # Setup environment file
    if [[ ! -f "${APP_DIR}/.env" ]]; then
        log_info "Creating .env file..."
        cp .env.example .env

        # Generate secret key
        SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
        sed -i "s/your-256-bit-random-key-here/${SECRET_KEY}/" .env

        log_warn "Please edit ${APP_DIR}/.env with your configuration"
        log_warn "Especially: DATABASE_URL, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET"
    fi

    # Set permissions
    chown -R www-data:www-data ${APP_DIR}
    chown -R www-data:www-data ${LOG_DIR}
    chmod 600 ${APP_DIR}/.env

    log_info "Application setup complete"
}

# =============================================================================
# Phase 5: Database Migrations
# =============================================================================
run_migrations() {
    log_info "Running database migrations..."

    cd ${APP_DIR}
    source venv/bin/activate

    # Run Alembic migrations if available
    if [[ -f "alembic.ini" ]]; then
        alembic upgrade head
    else
        log_warn "No Alembic migrations found. Tables will be created on first run."
    fi

    log_info "Migrations complete"
}

# =============================================================================
# Phase 6: Nginx Setup
# =============================================================================
setup_nginx() {
    log_info "Setting up Nginx..."

    # Copy Nginx configuration
    cp ${APP_DIR}/deploy/nginx.conf /etc/nginx/sites-available/${APP_NAME}

    # Enable site
    ln -sf /etc/nginx/sites-available/${APP_NAME} /etc/nginx/sites-enabled/

    # Remove default site
    rm -f /etc/nginx/sites-enabled/default

    # Test configuration
    nginx -t

    # Reload Nginx
    systemctl reload nginx

    log_info "Nginx setup complete"
}

# =============================================================================
# Phase 7: SSL Certificate
# =============================================================================
setup_ssl() {
    log_info "Setting up SSL certificate..."

    # Check if certificate already exists
    if [[ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
        log_info "SSL certificate already exists"
    else
        log_info "Obtaining SSL certificate from Let's Encrypt..."
        certbot --nginx -d ${DOMAIN} -d www.${DOMAIN} --non-interactive --agree-tos -m admin@${DOMAIN}
    fi

    # Setup auto-renewal
    systemctl enable certbot.timer
    systemctl start certbot.timer

    log_info "SSL setup complete"
}

# =============================================================================
# Phase 8: Systemd Service Setup
# =============================================================================
setup_service() {
    log_info "Setting up systemd service..."

    # Copy service file
    cp ${APP_DIR}/deploy/lawncare.service /etc/systemd/system/

    # Reload systemd
    systemctl daemon-reload

    # Enable and start service
    systemctl enable ${APP_NAME}
    systemctl start ${APP_NAME}

    # Check status
    sleep 2
    systemctl is-active --quiet ${APP_NAME} && log_info "Service is running" || log_error "Service failed to start"

    log_info "Service setup complete"
}

# =============================================================================
# Phase 9: Firewall Setup
# =============================================================================
setup_firewall() {
    log_info "Setting up firewall..."

    # Install ufw if not present
    apt install -y ufw

    # Configure firewall rules
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow 'Nginx Full'

    # Enable firewall
    ufw --force enable

    log_info "Firewall setup complete"
}

# =============================================================================
# Main
# =============================================================================
main() {
    log_info "Starting deployment for ${APP_NAME}..."

    case "${1:-all}" in
        system)
            setup_system
            ;;
        database)
            setup_database
            ;;
        redis)
            setup_redis
            ;;
        app)
            setup_application
            ;;
        migrations)
            run_migrations
            ;;
        nginx)
            setup_nginx
            ;;
        ssl)
            setup_ssl
            ;;
        service)
            setup_service
            ;;
        firewall)
            setup_firewall
            ;;
        all)
            setup_system
            setup_database
            setup_redis
            setup_application
            run_migrations
            setup_nginx
            setup_ssl
            setup_service
            setup_firewall
            ;;
        *)
            echo "Usage: $0 {system|database|redis|app|migrations|nginx|ssl|service|firewall|all}"
            exit 1
            ;;
    esac

    log_info "Deployment complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Edit ${APP_DIR}/.env with your configuration"
    echo "  2. Restart the service: systemctl restart ${APP_NAME}"
    echo "  3. Check logs: journalctl -u ${APP_NAME} -f"
    echo "  4. Test the API: curl https://${DOMAIN}/health"
}

main "$@"
