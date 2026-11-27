# The live EU demo on Hetzner + Neon (S9, FND-07)

Everything runs on **one Hetzner Cloud server in Germany**, deployed by **Coolify** (free, self-hosted) straight
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

Cost (check the price on screen before you buy): a Hetzner shared-vCPU server with 4 vCPU and 8 GB (CX33 or
the current equivalent) is about €6 to €9 a month with its IPv4 address; Neon's free plan; Coolify is free.

## Steps

Secrets never go into a chat, ticket or this repository: type or paste them only into Coolify.

1. **Hetzner server.** console.hetzner.com, new project `DekernAI`, Add Server: location Nuremberg or
   Falkenstein (Germany), image **Ubuntu 24.04**, type shared vCPU x86 **4 vCPU / 8 GB**, public IPv4 on,
   SSH key or root password (keep it in your password manager). Send back the server's **IPv4 address**.
2. **Firewall.** In Hetzner, Firewalls, create one allowing inbound TCP 22, 80, 443 and 8000 (8000 only until
   Coolify has its own domain), apply it to the server.
3. **Coolify.** Open the server's web Console in Hetzner (or SSH), log in as root, run the installer from
   coolify.io/docs (one `curl ... | bash` line). Open `http://<IPv4>:8000`, create the admin account.
4. **DNS at GoDaddy.** Add A records to the server's IPv4: `app` (the app) and `coolify` (Coolify's own admin).
   In Coolify, Settings, set the instance domain to `https://coolify.dekernai.com`, then close port 8000.
5. **Neon.** console.neon.tech, new project `dekernai-demo`, Postgres 16, region **AWS Europe (Frankfurt)**.
   Copy the connection string (pooled is fine). It becomes `DATABASE_URL` in step 7, written as
   `postgresql+psycopg://...` (replace `postgresql://` at the start) with `?sslmode=require` kept.
6. **Connect GitHub.** In Coolify, Sources, add a GitHub App, install it on `Payaml3/detent-mvp` only.
   New Resource, the repository, branch `main`, build pack **Docker Compose**, Base Directory `/`, Compose
   file `/infra/hetzner/docker-compose.yml`. Domains: `app` service `https://app.dekernai.com:8000`
   (Coolify routes port 8000 and gets the certificate), `site` service empty for now.
7. **Secrets.** The app refuses to start in demo mode without real secrets. In Coolify, Servers, your server,
   Terminal, paste this one line and press Enter. It prints six fresh secrets on your screen only (the same
   thing `make_secrets.py` does):

   ```
   python3 -c "import secrets as s,base64 as b;print(f'DEMO_PASSWORD={s.token_urlsafe(18)}\nSESSION_SECRET={s.token_hex(32)}\nAPI_KEY_PEPPER={s.token_hex(32)}\nCREDENTIALS_ENCRYPTION_KEY={b.urlsafe_b64encode(s.token_bytes(32)).decode()}\nMANDATE_SIGNING_KEY_DEMO={s.token_hex(32)}\nWEBHOOK_SECRET_PEPPER={s.token_hex(32)}')"
   ```

   Open the resource's Environment Variables, switch to the bulk (Developer) view, paste the six lines, add
   `DATABASE_URL=` with the Neon string from step 5, keep `DEMO_PASSWORD` in your password manager. Save, Deploy.
8. **Check.** Open `https://app.dekernai.com/healthz`: `database` must say `ok`. The chains say
   `not_configured`/`unreachable` until step 9; that is expected. Log in to `/console/login` with the
   `DEMO_PASSWORD` you pasted.
9. **Test wallets.** In Coolify, the `app` container's Terminal: `python infra/hetzner/make_secrets.py --wallets`.
   Paste the four `..._PRIVATE_KEY_...` lines into Environment Variables; the four addresses are safe to share.
   Get test ETH for gas from a Base Sepolia and an Ethereum Sepolia faucet for the two sending wallets and the
   two payer wallets. Then, in the app terminal: `detent demo token deploy --network base-sepolia` and
   `--network eth-sepolia`, set `USDC_ADDRESS_BASE_SEPOLIA` / `USDC_ADDRESS_ETH_SEPOLIA` to the printed
   addresses, redeploy, then `detent demo token fund --network <n>` and `detent demo check`.
10. **AI agents.** Create an Anthropic API key at console.anthropic.com (set a monthly spend limit), paste it as
    `ANTHROPIC_API_KEY`, redeploy. Until then the agents use recorded stand-ins (`AGENT_LLM=auto`).
11. **Website (optional, last).** Set the `site` service domain to `https://dekernai.com,https://www.dekernai.com`,
    then at GoDaddy point `@` and `www` to the server instead of Vercel. Keep Vercel until the new one loads.

## Operating it

- Deploys: every push to `main` redeploys (Coolify webhook). Rollback: Coolify, Deployments, redeploy an older one.
- Logs and a shell per container: Coolify, the resource, Logs / Terminal.
- Restore (OPS-03): Neon point-in-time restore to a new branch, `detent audit verify`, switch `DATABASE_URL`.
- Run locally: `docker compose --project-directory . -f infra/hetzner/docker-compose.yml build`.
