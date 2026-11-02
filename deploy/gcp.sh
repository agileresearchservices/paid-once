#!/usr/bin/env bash
# One VM on Google Cloud that serves the demo at https://<ip>.sslip.io behind one shared password.
# Usage: deploy/gcp.sh create | update | stop | start | status | logs | destroy
# Needs: gcloud signed in, a project with billing, and (for `create`) ANTHROPIC_API_KEY and PAIDONCE_PANEL_PASSWORD
# in the environment. They go to Secret Manager and nowhere else.
set -euo pipefail

PROJECT="${PAIDONCE_GCP_PROJECT:-paid-once-demo}"
ZONE="${PAIDONCE_GCP_ZONE:-us-central1-a}"
REGION="${ZONE%-*}"
VM="${PAIDONCE_GCP_VM:-paidonce}"
MACHINE="${PAIDONCE_GCP_MACHINE:-e2-medium}"
G=(gcloud --project "$PROJECT")
HERE="$(cd "$(dirname "$0")" && pwd)"

put_secret() {  # name value: create the secret if needed, add a new version
  "${G[@]}" secrets describe "$1" >/dev/null 2>&1 || "${G[@]}" secrets create "$1" --replication-policy=automatic >/dev/null
  printf '%s' "$2" | "${G[@]}" secrets versions add "$1" --data-file=- >/dev/null
}

ip_of() { "${G[@]}" compute addresses describe "$VM-ip" --region "$REGION" --format='value(address)'; }

case "${1:-}" in
  create)
    : "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY (the key the hosted demo will spend)}"
    : "${PAIDONCE_PANEL_PASSWORD:?set PAIDONCE_PANEL_PASSWORD (the shared password, user name: panel)}"
    "${G[@]}" services enable compute.googleapis.com secretmanager.googleapis.com >/dev/null
    put_secret anthropic-api-key "$ANTHROPIC_API_KEY"
    put_secret paidonce-password "$PAIDONCE_PANEL_PASSWORD"
    "${G[@]}" compute addresses describe "$VM-ip" --region "$REGION" >/dev/null 2>&1 ||
      "${G[@]}" compute addresses create "$VM-ip" --region "$REGION" >/dev/null
    IP="$(ip_of)"; HOST="${IP//./-}.sslip.io"
    "${G[@]}" compute firewall-rules describe "$VM-web" >/dev/null 2>&1 ||
      "${G[@]}" compute firewall-rules create "$VM-web" --allow tcp:80,tcp:443 --target-tags "$VM-web" >/dev/null
    NUM="$("${G[@]}" projects describe "$PROJECT" --format='value(projectNumber)')"
    for s in anthropic-api-key paidonce-password; do  # the VM's service account reads these two secrets and nothing else
      "${G[@]}" secrets add-iam-policy-binding "$s" --member "serviceAccount:$NUM-compute@developer.gserviceaccount.com" \
        --role roles/secretmanager.secretAccessor >/dev/null
    done
    "${G[@]}" compute instances create "$VM" --zone "$ZONE" --machine-type "$MACHINE" --address "$IP" \
      --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud --boot-disk-size 30GB \
      --tags "$VM-web" --scopes cloud-platform \
      --metadata "hostname=$HOST" --metadata-from-file startup-script="$HERE/startup.sh"
    echo "Created. The first boot installs everything (about 10 minutes): ./deploy/gcp.sh logs"
    echo "Then open https://$HOST  (user: panel)"
    ;;
  update)  # pull the latest main and rebuild: re-run the startup script
    "${G[@]}" compute ssh "$VM" --zone "$ZONE" --command 'sudo google_metadata_script_runner startup'
    ;;
  stop)    "${G[@]}" compute instances stop "$VM" --zone "$ZONE" ;;
  start)   "${G[@]}" compute instances start "$VM" --zone "$ZONE"; echo "https://$(ip_of | tr . -).sslip.io" ;;
  status)  "${G[@]}" compute instances describe "$VM" --zone "$ZONE" --format='value(status)'; echo "https://$(ip_of | tr . -).sslip.io" ;;
  logs)    "${G[@]}" compute ssh "$VM" --zone "$ZONE" --command 'sudo tail -n 60 /var/log/paidonce-startup.log; systemctl status paidonce --no-pager | head -15' ;;
  destroy)
    "${G[@]}" compute instances delete "$VM" --zone "$ZONE" --quiet
    "${G[@]}" compute addresses delete "$VM-ip" --region "$REGION" --quiet
    "${G[@]}" compute firewall-rules delete "$VM-web" --quiet
    echo "VM, address and firewall rule deleted. Secrets remain: gcloud secrets delete anthropic-api-key paidonce-password"
    ;;
  *) sed -n '2,5p' "$0"; exit 1 ;;
esac
