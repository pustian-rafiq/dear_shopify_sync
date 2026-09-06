#!/bin/bash
set -e

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "Error: docker compose is not installed." >&2
  exit 1
fi

DOMAINS=("apps.f4ip.com")
EMAIL="mamun@sgcsoft.net"
DATA_PATH="./certbot"
WEBROOT_PATH="/var/www/certbot"
CERTBOT_SERVICE="certbot"
NGINX_SERVICE="nginx"
PRIMARY_DOMAIN="${DOMAINS[0]}"
STAGING=0 # Set to 1 for testing, 0 for production

if [ -d "$DATA_PATH/conf/live/$PRIMARY_DOMAIN" ]; then
  read -p "Existing certificate found for $PRIMARY_DOMAIN. Replace it? (y/N) " decision
  if [ "$decision" != "Y" ] && [ "$decision" != "y" ]; then
    echo "Aborting certificate issuance."
    exit 0
  fi
fi

if [ ! -f "$DATA_PATH/conf/options-ssl-nginx.conf" ] || [ ! -f "$DATA_PATH/conf/ssl-dhparams.pem" ]; then
  echo "Downloading recommended TLS parameters..."
  mkdir -p "$DATA_PATH/conf"
  curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf > "$DATA_PATH/conf/options-ssl-nginx.conf"
  curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot/ssl-dhparams.pem > "$DATA_PATH/conf/ssl-dhparams.pem"
fi

echo "Checking Nginx service..."
if ! $COMPOSE ps | grep -q "$NGINX_SERVICE"; then
  echo "Starting Nginx..."
  $COMPOSE up -d "$NGINX_SERVICE"
fi

echo "Requesting Let's Encrypt certificate for ${DOMAINS[*]}..."
domain_args=""
for domain in "${DOMAINS[@]}"; do
  domain_args="$domain_args -d $domain"
done

email_arg="--email $EMAIL"
if [ -z "$EMAIL" ]; then
  email_arg="--register-unsafely-without-email"
fi

staging_arg=""
if [ "$STAGING" != "0" ]; then
  staging_arg="--staging"
fi

$COMPOSE run --rm --entrypoint "\
  certbot certonly --webroot -w $WEBROOT_PATH \
  $staging_arg \
  $email_arg \
  $domain_args \
  --rsa-key-size 4096 \
  --agree-tos \
  --non-interactive" "$CERTBOT_SERVICE"

CERT_PATH="/etc/letsencrypt/live/$PRIMARY_DOMAIN/fullchain.pem"
PRIVKEY_PATH="/etc/letsencrypt/live/$PRIMARY_DOMAIN/privkey.pem"
if $COMPOSE run --rm --entrypoint "test -f $CERT_PATH && test -f $PRIVKEY_PATH" "$CERTBOT_SERVICE"; then
  echo "Certificate files verified at $CERT_PATH and $PRIVKEY_PATH."
else
  echo "Error: Certificate files not found. Check Certbot configuration." >&2
  exit 1
fi

echo "Reloading Nginx..."
$COMPOSE exec "$NGINX_SERVICE" nginx -s reload

echo "SSL setup complete! Access your site at https://$PRIMARY_DOMAIN"
