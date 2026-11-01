FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Where the Next.js server proxies /api/* (internal Docker network name). Baked into the build.
ARG BACKEND_URL=http://api:8000
ENV BACKEND_URL=$BACKEND_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S flowqr && adduser -S flowqr -G flowqr
COPY --from=build --chown=flowqr:flowqr /app/.next/standalone ./
COPY --from=build --chown=flowqr:flowqr /app/.next/static ./.next/static
COPY --from=build --chown=flowqr:flowqr /app/public ./public
USER flowqr
EXPOSE 3000
CMD ["node", "server.js"]
