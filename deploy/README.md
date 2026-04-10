# Cortex UI — Deploy

## First deploy

```bash
# On ThinkPad — sync code
cd /home/dan/projects/cortex && git pull

# Install API deps
python3 -m venv api/.venv
api/.venv/bin/pip install -r api/requirements.txt

# Build frontend (set API URL to the ThinkPad hostname)
cd web && npm install && VITE_API_URL=http://cortex.dkvs8001.org npm run build && cd ..

# Install and start systemd services
sudo cp deploy/cortex-api.service /etc/systemd/system/
sudo cp deploy/cortex-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cortex-api cortex-web

# Add Caddy vhost — append deploy/caddy-cortex.conf to Caddyfile
# then reload Caddy (adjust path to your docker-compose):
cat deploy/caddy-cortex.conf >> ~/docker/caddy/Caddyfile
cd ~/docker && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

## Updates

```bash
cd /home/dan/projects/cortex && git pull
cd web && VITE_API_URL=http://cortex.dkvs8001.org npm run build && cd ..
sudo systemctl restart cortex-api cortex-web
```

## Status check

```bash
sudo systemctl status cortex-api cortex-web
```
