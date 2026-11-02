# Hosting the demo on Google Cloud

One small VM serves the demo at `https://<ip>.sslip.io` behind one shared password. It runs exactly what `make demo` runs
locally: the show server on `127.0.0.1:8100`, which starts and kills its own services. Caddy in front adds HTTPS and the
password. Nobody has to install anything, and everyone who prefers can still install locally (see the README).

**One shared show.** The VM has one scoreboard and one running scene. Reset wipes it for everyone, and two people
clicking at once will collide. Treat it as one person driving, or agree who goes when.

**Cost.** An `e2-medium` is about $25 a month while running, plus the model calls each Run makes on the key you give
it. Set a spend limit on that key in the Anthropic console. `deploy/gcp.sh stop` pauses the VM; `destroy` removes it.

## Create it

```bash
gcloud auth login you@example.com
gcloud projects create my-paidonce-demo && gcloud billing projects link my-paidonce-demo --billing-account=ACCOUNT_ID
export PAIDONCE_GCP_PROJECT=my-paidonce-demo
export ANTHROPIC_API_KEY=...           # goes to Secret Manager only
export PAIDONCE_PANEL_PASSWORD=...     # the shared password; the user name is `panel`
deploy/gcp.sh create
deploy/gcp.sh logs                     # the first boot takes about ten minutes
```

`create` enables Compute and Secret Manager, stores the two secrets, reserves a static address, opens ports 80 and 443,
and starts the VM. `deploy/startup.sh` then installs the tools the README lists, builds the UI from `main`, and runs the
show as the `paidonce` systemd service. Caddy gets its certificate for the `sslip.io` name on first request.

## Day to day

| Command | What it does |
|---|---|
| `deploy/gcp.sh status` | VM state and the URL |
| `deploy/gcp.sh update` | Pull the latest `main`, rebuild the UI, restart the show |
| `deploy/gcp.sh stop` / `start` | Pause and resume (the address and URL stay the same) |
| `deploy/gcp.sh logs` | Last lines of the install log and the service status |
| `deploy/gcp.sh destroy` | Delete the VM, address and firewall rule |

Defaults: zone `us-central1-a`, VM `paidonce`, machine `e2-medium`; override with `PAIDONCE_GCP_ZONE`, `PAIDONCE_GCP_VM`
and `PAIDONCE_GCP_MACHINE`. To change the password or key, add a new secret version
(`gcloud secrets versions add paidonce-password --data-file=-`) and run `deploy/gcp.sh update`.

## What it does not do

No per-visitor isolation, no custom domain (add one by editing the Caddyfile host in `deploy/startup.sh`), no backups
(the ledger is rebuilt by each run), and no protection beyond the shared password and the key's spend limit.
