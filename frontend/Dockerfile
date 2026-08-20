# Multi-stage build: Vite (node) → nginx:alpine on port 8080 (Cloud Run).
# Mirrors the おたよりナビ (toddler-private-rag) frontend deploy shape.

# --- build stage ---
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# --- production stage ---
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY start-nginx.sh /start-nginx.sh
RUN chmod +x /start-nginx.sh
EXPOSE 8080
ENTRYPOINT ["/start-nginx.sh"]
