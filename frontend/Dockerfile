# ---- Build stage ----
FROM node:20-alpine AS builder
WORKDIR /app
# Accept Shopify API key at build time so Vite can embed it in the bundle
ARG VITE_SHOPIFY_API_KEY=""
ENV VITE_SHOPIFY_API_KEY=$VITE_SHOPIFY_API_KEY
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

# ---- Serve stage ----
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# nginx:alpine processes /etc/nginx/templates/*.template via envsubst at startup
# Set API_HOST env var (default: oms_api for the main stack)
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV API_HOST=oms_api
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
