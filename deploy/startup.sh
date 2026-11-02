#!/usr/bin/env bash
# Runs as root on the VM's first boot (GCE startup script). Installs the same tools the README does, builds the UI,
# runs the show as a systemd service on 127.0.0.1:8100 and puts Caddy (HTTPS + one shared password) in front of it.
# Reads two Secret Manager secrets with the VM's own service account: anthropic-api-key and paidonce-password.
set -euo pipefail
exec > >(tee -a /var/log/paidonce-startup.log) 2>&1

REPO=https://github.com/agileresearchservices/paid-once.git
APP=paidonce
HOME_DIR=/home/$APP
SRC=$HOME_DIR/paid-once
BREW=/home/linuxbrew/.linuxbrew

md() { curl -fsS -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/$1"; }
PROJECT=$(md project/project-id)
HOST=$(md instance/attributes/hostname)
TOKEN=$(md instance/service-accounts/default/token | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
secret() {
  curl -fsS -H "Authorization: Bearer $TOKEN" \
    "https://secretmanager.googleapis.com/v1/projects/$PROJECT/secrets/$1/versions/latest:access" |
    python3 -c 'import sys,json,base64; print(base64.b64decode(json.load(sys.stdin)["payload"]["data"]).decode(), end="")'
}

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq build-essential procps curl file git debian-keyring debian-archive-keyring apt-transport-https gpg

# Caddy from its own apt repo (Ubuntu's copy is too old for `basic_auth`).
if ! command -v caddy >/dev/null; then
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt >/etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy
fi

# The service user installs Homebrew, which needs passwordless sudo only while it runs.
id $APP >/dev/null 2>&1 || useradd -m -s /bin/bash $APP
echo "$APP ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/90-$APP-install
if [ ! -x $BREW/bin/brew ]; then
  su - $APP -c 'NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
fi
su - $APP -c "$BREW/bin/brew install temporal uv node"
rm -f /etc/sudoers.d/90-$APP-install

# Code: clone once, then fast-forward on every boot, so `gcp.sh update` is just a restart of this script.
if [ ! -d "$SRC/.git" ]; then su - $APP -c "git clone -q $REPO $SRC"; else su - $APP -c "cd $SRC && git pull -q --ff-only"; fi
su - $APP -c "export PATH=$BREW/bin:\$PATH && cd $SRC && make install && make ui"

# Secrets: the key goes to a root-owned env file the service reads; the password becomes a bcrypt hash for Caddy.
install -m 600 -o $APP -g $APP /dev/null /etc/paidonce.env
printf 'ANTHROPIC_API_KEY=%s\n' "$(secret anthropic-api-key)" >/etc/paidonce.env
HASH=$(caddy hash-password --plaintext "$(secret paidonce-password)")

cat >/etc/systemd/system/paidonce.service <<UNIT
[Unit]
Description=paid-once demo (show server and the services it owns)
After=network-online.target
Wants=network-online.target

[Service]
User=$APP
WorkingDirectory=$SRC
EnvironmentFile=/etc/paidonce.env
Environment=PATH=$BREW/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$BREW/bin/uv run python -m paidonce.show
Restart=on-failure
RestartSec=5
# The show starts each service in its own session; stop them all with it.
KillMode=control-group

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/caddy/Caddyfile <<CADDY
$HOST {
	# Chrome fetches the tab icon without the page's password, so /brand/* (two logo files from the public repo) is open.
	@private not path /brand/*
	basic_auth @private {
		panel $HASH
	}
	reverse_proxy 127.0.0.1:8100 {
		flush_interval -1
	}
}
CADDY

systemctl daemon-reload
systemctl enable --now paidonce
systemctl restart paidonce
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy
echo "paidonce ready at https://$HOST"
