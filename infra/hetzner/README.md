# The live EU demo on Hetzner + Neon (S9, FND-07)

Everything runs on **one Hetzner Cloud server in Helsinki, Finland (EU)**, deployed by **Coolify** (free, self-hosted) straight
from GitHub. The database is **Neon Postgres in AWS Europe (Frankfurt) `eu-central-1`**. Test networks and test
keys only (invariant 14). This replaces the Render plan in `render.yaml`, which was never deployed.

| Container | What | Public address |
|---|---|---|
| `app` | API (`/v1`), back-office console (`/console`), client dashboard (`/dashboard`), admin (`/admin`), `/healthz`. Runs migrations and the idempotent seed on start | `https://app.dekernai.com` |
| `worker` | Job loop: sends, confirmations, deadlines, deposits, reconciliation, webhooks | none |
| `banksim` | Simulated instant bank rail | none (private) |
| `faultproxy` | Fault injection in front of Base Sepolia, `FAULTPROXY_DEMO_MODE=1` | none (private) |
| `site` | Marketing site (Astro, static, nginx) | `https://dekernai.com` (when moved from Vercel) |

Files: `docker-compose.yml` (what Coolify deploys), `Dockerfile.app`, `Dockerfile.site`, `nginx-site.conf`,
`make_secrets.py` (prints fresh secrets and test wallets on your own screen).

Cost: a Hetzner Cost-Optimized **CAX11** (Arm64, 2 vCPU, 4 GB) at about €7.79 a month with its IPv4 address
(Nov 2026, incl. VAT); Neon's free plan; Coolify is free. Grow it later with Hetzner's Rescale ("CPU and RAM
only", so it can shrink again). Every dependency ships Arm64 wheels, so the images build the same on Arm.

## Steps

Secrets never go into a chat, ticket or this repository: type or paste them only into Coolify.

Server details (its IP address, root access, the Coolify admin login) live only in Hetzner, Coolify, GoDaddy
and your password manager. Never commit them to this repository.

1. **SSH key (on your own computer).** In Windows PowerShell: `ssh-keygen -t ed25519` and press Enter three
   times. Then `Get-Content $HOME\.ssh\id_ed25519.pub` prints your **public** key (safe to paste into Hetzner;
   the private file `id_ed25519` never leaves your computer).
2. **Hetzner server.** console.hetzner.com, new project `DekernAI`, Add Server: Cost-Optimized, Arm64,
   **CAX11**, location **Helsinki** (where it was in stock; any EU location works, then update `HOSTING_REGION`),
   image **Ubuntu 24.04**, public IPv4 on,
   **SSH keys: add the public key from step 1**. With a key chosen, Hetzner sets no root password and password
   login is off.
3. **Firewall.** Hetzner, Firewalls, Create: inbound TCP **22** (SSH; set Source to your own IP address if it
   is stable), **80** and **443** (web), plus **8000** only for the first Coolify login. Apply it to the server.
4. **Coolify.** `ssh root@<server IP>` from PowerShell, then run the installer one-liner from coolify.io/docs.
   Open `http://<server IP>:8000` straight away and create the admin account (the first visitor becomes admin),
   with a long password from your password manager, and turn on two-factor login in your Coolify profile.
5. **DNS at GoDaddy, then close port 8000.** Add A records to the server IP: `app` (the app) and a
   non-obvious subdomain for Coolify's admin, chosen by the founder and kept out of this repository (it is
   recorded only in the password manager). In Coolify, Settings, set the instance domain to it over `https://`; once that
   opens over HTTPS, delete the 8000 rule from the Hetzner firewall. Only 22, 80 and 443 stay open.
6. **Neon.** console.neon.tech, new project `dekernai-demo`, Postgres 16, region **AWS Europe (Frankfurt)**.
   Copy the connection string (pooled is fine). It becomes `DATABASE_URL` in step 8, written as
   `postgresql+psycopg://...` (replace `postgresql://` at the start) with `?sslmode=require` kept.
7. **Connect GitHub (the repository is private).** In Coolify, Sources, **+ Add**, GitHub App, keep the
   default name, Register. GitHub opens: create the app on your personal account, then on Install choose
   **Only select repositories**, `Payaml3/detent-mvp`, Install. Coolify then reads the private repository
   and gets a push webhook, with no deploy key or token to copy. In your project, **+ New Resource**,
   **Private Repository (with GitHub App)**, the app, the repository, branch `main`, build pack **Docker Compose**, Base Directory `/`, Compose
   file `/infra/hetzner/docker-compose.yml`. Domains: `app` service `https://app.dekernai.com:8000`
   (Coolify routes port 8000 and gets the certificate), `site` service empty for now.
8. **Secrets.** The app refuses to start in demo mode without real secrets. In Coolify, Servers, your server,
   Terminal, paste this one line and press Enter. It prints six fresh secrets on your screen only (the same
   thing `make_secrets.py` does):

   ```
   python3 -c "import secrets as s,base64 as b;print(f'DEMO_PASSWORD={s.token_urlsafe(18)}\nSESSION_SECRET={s.token_hex(32)}\nAPI_KEY_PEPPER={s.token_hex(32)}\nCREDENTIALS_ENCRYPTION_KEY={b.urlsafe_b64encode(s.token_bytes(32)).decode()}\nMANDATE_SIGNING_KEY_DEMO={s.token_hex(32)}\nWEBHOOK_SECRET_PEPPER={s.token_hex(32)}')"
   ```

   Open the resource's Environment Variables, switch to the bulk (Developer) view, paste the six lines, add
   `DATABASE_URL=` with the Neon string from step 6, keep `DEMO_PASSWORD` in your password manager. Save, Deploy.
9. **Check.** Open `https://app.dekernai.com/healthz`: `database` must say `ok`. The chains say
   `not_configured`/`unreachable` until step 10; that is expected. Log in to `/console/login` with the
   `DEMO_PASSWORD` you pasted.
10. **Test wallets.** In Coolify, the `app` container's Terminal: `python infra/hetzner/make_secrets.py --wallets`.
   Paste the four `..._PRIVATE_KEY_...` lines into Environment Variables; the four addresses are safe to share.
   Get test ETH for gas from a Base Sepolia and an Ethereum Sepolia faucet for the two sending wallets and the
   two payer wallets. Then, in the app terminal: `detent demo token deploy --network base-sepolia` and
   `--network eth-sepolia`, set `USDC_ADDRESS_BASE_SEPOLIA` / `USDC_ADDRESS_ETH_SEPOLIA` to the printed
   addresses, redeploy, then `detent demo token fund --network <n>` and `detent demo check`.
11. **AI agents.** Create an Anthropic API key at console.anthropic.com (set a monthly spend limit), paste it as
    `ANTHROPIC_API_KEY`, redeploy. Until then the agents use recorded stand-ins (`AGENT_LLM=auto`).
12. **Website (optional, last).** Set the `site` service domain to `https://dekernai.com,https://www.dekernai.com`,
    then at GoDaddy point `@` and `www` to the server instead of Vercel. Keep Vercel until the new one loads.

## Operating it

- Deploys: every push to `main` redeploys (Coolify webhook). Rollback: Coolify, Deployments, redeploy an older one.
- Logs and a shell per container: Coolify, the resource, Logs / Terminal.
- Restore (OPS-03): Neon point-in-time restore to a new branch, `detent audit verify`, switch `DATABASE_URL`.
- Run locally: `docker compose --project-directory . -f infra/hetzner/docker-compose.yml build`.
