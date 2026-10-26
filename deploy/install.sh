#!/usr/bin/env bash
set -euo pipefail

app_dir=/opt/allsewpattern
transfer_dir=/root/allsewpattern-transfer
if ! id allsewpattern >/dev/null 2>&1; then
    useradd --system --home-dir "$app_dir" --shell /usr/sbin/nologin allsewpattern
fi
install -d -m 755 "$app_dir"
tar -xzf "$transfer_dir/release.tar.gz" -C "$app_dir"
install -d -o allsewpattern -g allsewpattern -m 750 "$app_dir/data"
if [ ! -f "$app_dir/data/patternhub.sqlite3" ]; then
    install -o allsewpattern -g allsewpattern -m 600 "$transfer_dir/catalog.sqlite3" "$app_dir/data/patternhub.sqlite3"
fi
install -o root -g allsewpattern -m 640 "$transfer_dir/deploy.env" "$app_dir/.env"
python3 -m venv "$app_dir/.venv"
"$app_dir/.venv/bin/python" -m pip install -q -r "$app_dir/requirements-web.txt"
install -m 644 "$app_dir/deploy/allsewpattern-bot.service" /etc/systemd/system/
install -m 644 "$app_dir/deploy/allsewpattern-web.service" /etc/systemd/system/
install -m 644 "$app_dir/deploy/allsewpattern-refresh.service" /etc/systemd/system/
install -m 644 "$app_dir/deploy/allsewpattern-refresh.timer" /etc/systemd/system/
install -m 644 "$app_dir/deploy/nginx.conf" /etc/nginx/sites-available/allsewpattern
ln -sfn /etc/nginx/sites-available/allsewpattern /etc/nginx/sites-enabled/allsewpattern
systemctl daemon-reload
systemctl enable --now allsewpattern-web
nginx -t
systemctl reload nginx
certbot --nginx -d allsewpattern.2.56.240.132.sslip.io --non-interactive --agree-tos --register-unsafely-without-email --redirect
systemctl enable --now allsewpattern-bot allsewpattern-refresh.timer
systemctl --no-pager is-active allsewpattern-bot allsewpattern-web nginx
