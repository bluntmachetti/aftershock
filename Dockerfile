# Stage 1: build the observatory frontend
FROM node:22-slim AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: the server
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ src/
RUN uv sync --frozen --no-dev
COPY bench/ bench/
COPY --from=web /build/dist web/dist
RUN mkdir -p /data/runs

EXPOSE 8788
VOLUME ["/data/runs"]
# DASHSCOPE_API_KEY is supplied at runtime (env/--env-file); never baked into the image.
CMD ["uv", "run", "--no-sync", "aftershock", "serve", "--host", "0.0.0.0", "--port", "8788", "--runs-dir", "/data/runs"]
