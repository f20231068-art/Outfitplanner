# The web app (Next.js). Build context is the REPO ROOT (the npm lockfile lives there):
#   docker build -f apps/web/Dockerfile -t stylist-web .
#
# NEXT_PUBLIC_API_URL is baked into the page code at build time. The default, empty, means "the API is on
# the same address as this page" (the reverse proxy sends /auth, /conversations... to the API). That
# same-address setup is what lets the login cookie work without buying a domain.

FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY apps/mastra/package.json apps/mastra/package.json
RUN npm ci -w apps/web
COPY apps/web apps/web
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build -w apps/web

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app /app
USER node
EXPOSE 3000
CMD ["node", "node_modules/next/dist/bin/next", "start", "apps/web", "-H", "0.0.0.0", "-p", "3000"]
