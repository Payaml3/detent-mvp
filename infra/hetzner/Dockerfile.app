# DekernAI back office: API + console + dashboard, worker, bank simulator, fault proxy (one image, four commands).
# Built by Coolify on the Hetzner server from infra/hetzner/docker-compose.yml. Test networks and test keys only.

# The demo test token (chain/src/MockUSDC.sol), compiled once here so `detent demo token deploy` works in the
# image without Foundry. Multi-arch image (amd64 and arm64, for the CAX11).
FROM ghcr.io/foundry-rs/foundry:v1.7.1 AS contracts
USER root
WORKDIR /chain
COPY chain/foundry.toml ./
COPY chain/src ./src
RUN forge build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir "uv==0.11.32"

WORKDIR /app
# Dependencies first, so a code-only change reuses this layer.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/banksim/pyproject.toml apps/banksim/pyproject.toml
COPY apps/faultproxy/pyproject.toml apps/faultproxy/pyproject.toml
COPY eval/pyproject.toml eval/pyproject.toml
COPY sdks/python/pyproject.toml sdks/python/pyproject.toml
RUN uv sync --frozen --all-packages --no-dev --no-install-workspace

COPY . .
COPY --from=contracts /chain/out ./chain/out
RUN uv sync --frozen --all-packages --no-dev \
 && useradd --system --uid 10001 detent \
 && chown -R detent /app
USER detent

EXPOSE 8000
CMD ["detent", "api", "--host", "0.0.0.0", "--port", "8000"]
