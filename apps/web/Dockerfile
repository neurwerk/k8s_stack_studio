# syntax=docker/dockerfile:1
#
# k8s-stack-studio-web — Next.js frontend for the AI Stack Studio dashboard.
#
# Multi-stage build:
#   1. Build stage:  install dependencies, run `next build`
#   2. Runtime stage: copy standalone output, run as non-root
#
# Build context: repository root (needs pnpm-workspace.yaml + pnpm-lock.yaml)

# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder

# Enable corepack so pnpm is available
RUN corepack enable && corepack prepare pnpm@9.15.4 --activate

WORKDIR /build

# Copy root workspace files (pnpm needs these to resolve the monorepo)
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json turbo.json ./

# Copy only the web app source (no node_modules)
COPY apps/web/package.json apps/web/tsconfig.json apps/web/next.config.ts apps/web/postcss.config.mjs ./apps/web/
COPY apps/web/app/ ./apps/web/app/
COPY apps/web/components/ ./apps/web/components/
COPY apps/web/lib/ ./apps/web/lib/

# Install dependencies (frozen lockfile for reproducibility)
RUN pnpm install --frozen-lockfile

# Build the Next.js app (produces .next/standalone + .next/static)
RUN pnpm --filter web run build

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM node:22-alpine AS runtime

LABEL org.opencontainers.image.source="https://github.com/neurwerk/k8s_stack_studio"
LABEL org.opencontainers.image.description="k8s-stack-studio-web — AI Stack Studio frontend"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Create non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy standalone server and static assets from the build stage
COPY --from=builder /build/apps/web/.next/standalone ./
COPY --from=builder /build/apps/web/.next/static ./apps/web/.next/static

# Copy the runtime entrypoint that injects per-deployment OIDC config
COPY apps/web/docker-entrypoint.sh /app/
COPY apps/web/scripts/write-runtime-env.mjs /app/
COPY LICENSE /licenses/LICENSE
RUN chmod +x /app/docker-entrypoint.sh

# Ensure the non-root user owns the app directory
RUN chown -R nextjs:nodejs /app

USER nextjs

EXPOSE 3000

ENV NODE_ENV=production
ENV PORT=3000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
