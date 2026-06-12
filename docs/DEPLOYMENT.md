# Deployment

Aftershock runs as a Docker Compose stack:

- `aftershock`: FastAPI + built React observatory on port `8788`
- `caddy`: public reverse proxy on ports `80` and `443`

Caddy terminates HTTPS and forwards all traffic to `aftershock:8788`, so the public URL is a normal
`https://<hostname>` address instead of `http://<ip>:8788`.

## Alibaba Cloud Friendly URL

1. Pick the public hostname, for example `aftershock.example.com`.
2. In Alibaba Cloud DNS, or wherever the domain is hosted, create an `A` record from that hostname
   to the ECS instance public IPv4 address.
3. In the ECS security group, allow inbound TCP `80` and `443`. Keep `8788` closed publicly; Compose
   binds it to `127.0.0.1` for on-box debugging only.
4. On the server, create `.env` from `.env.example`:

   ```bash
   cp .env.example .env
   ```

   Set at least:

   ```dotenv
   DASHSCOPE_API_KEY=...
   OBSERVATORY_TOKEN=...
   AFTERSHOCK_HOSTNAME=aftershock.example.com
   OBSERVATORY_ORIGIN=https://aftershock.example.com
   ```

5. Rebuild and restart:

   ```bash
   docker compose up -d --build
   ```

6. Check the deployment:

   ```bash
   docker compose ps
   docker compose logs --tail=100 caddy
   curl -I https://aftershock.example.com
   ```

7. Open the observatory with the one-time token URL:

   ```text
   https://aftershock.example.com/?token=<OBSERVATORY_TOKEN>
   ```

   The frontend stores the token locally and removes it from the address bar.

## Notes

- Caddy automatically requests and renews TLS certificates when `AFTERSHOCK_HOSTNAME` resolves to
  the server and ports `80`/`443` are reachable.
- The app uses relative `/api` and `/ws` paths, so no frontend rebuild is needed when the hostname
  changes.
- If DNS is still propagating, Caddy may log ACME errors. Restarting is not usually necessary; it
  retries certificate issuance.
