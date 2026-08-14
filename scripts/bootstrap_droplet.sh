#!/usr/bin/env bash
# One-time root bootstrap on the DO droplet for Mahogany STG.
# Reuses existing /root/mahogany/.env — does NOT rotate secrets.
# Usage (on droplet as root):
#   bash scripts/bootstrap_droplet.sh
set -euo pipefail

APP=/opt/mahogany
DATA=/var/lib/mahogany
ENV_FILE=/etc/mahogany.env
LEGACY=/root/mahogany
DEPLOY_USER=deploy

echo "== dirs =="
mkdir -p "$APP" "$DATA"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP" "$DATA"

echo "== env (reuse legacy, no rotation) =="
if [[ -f "$ENV_FILE" ]]; then
  echo "Keeping existing $ENV_FILE"
else
  if [[ -f "$LEGACY/.env" ]]; then
    cp "$LEGACY/.env" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "Copied $LEGACY/.env → $ENV_FILE"
  else
    echo "WARN: no $LEGACY/.env — create $ENV_FILE manually" >&2
  fi
fi

# Ensure runtime paths for new package
if ! grep -q '^MAHOGANY_DATA_DIR=' "$ENV_FILE" 2>/dev/null; then
  printf '\nMAHOGANY_DATA_DIR=%s\nMAHOGANY_LANDING_SRC=%s/landing/index.html\nMAHOGANY_LANDING_DEST=/var/www/mahogany/index.html\nMAHOGANY_HEALTH_PORT=3004\n' \
    "$DATA" "$APP" >> "$ENV_FILE"
fi

echo "== copy runtime state from legacy (sessions / dedup) =="
for f in ig_session.json ig_seen.json ig_rotation.json seen_articles.json \
         listings_seen.json rentals_seen.json bot_runs.json hoa_seen.json \
         .group_bot_offset; do
  if [[ -f "$LEGACY/$f" && ! -f "$DATA/$f" ]]; then
    cp "$LEGACY/$f" "$DATA/$f"
    chown "$DEPLOY_USER:$DEPLOY_USER" "$DATA/$f"
    echo "  copied $f"
  fi
done

echo "== mahogany-restart helper =="
cat > /usr/local/bin/mahogany-restart <<'EOF'
#!/bin/bash
set -euo pipefail
/usr/bin/systemctl restart mahogany-health
/usr/bin/systemctl is-active mahogany-health
EOF
chmod 755 /usr/local/bin/mahogany-restart

echo "== sudoers for deploy =="
cat > /etc/sudoers.d/mahogany-deploy <<EOF
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/local/bin/mahogany-restart, /usr/bin/systemctl restart mahogany-health, /usr/bin/systemctl status mahogany-health, /usr/bin/systemctl is-active mahogany-health, /usr/bin/systemctl start mahogany-health, /usr/bin/systemctl enable mahogany-health, /usr/bin/systemctl daemon-reload
EOF
chmod 440 /etc/sudoers.d/mahogany-deploy

echo "== nginx STG server (nip.io + build-id proxy) =="
cat > /etc/nginx/sites-available/mahogany-stg <<'EOF'
server {
    listen 80;
    server_name mahogany.64.225.115.88.nip.io;

    root /var/www/mahogany;
    index index.html;

    location /api/build-id {
        proxy_pass http://127.0.0.1:3004/api/build-id;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

    location /healthz {
        proxy_pass http://127.0.0.1:3004/healthz;
        proxy_http_version 1.1;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF
ln -sfn /etc/nginx/sites-available/mahogany-stg /etc/nginx/sites-enabled/mahogany-stg
nginx -t
systemctl reload nginx

echo "== landing ownership for deploy updates =="
chown -R "$DEPLOY_USER:$DEPLOY_USER" /var/www/mahogany || true

echo "Bootstrap OK. Legacy /root/mahogany timers left untouched."
echo "Next: deploy user rsyncs app → $APP and starts mahogany-health."
