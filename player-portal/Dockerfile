# Stage 1: build the player portal (Vite/React)
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci || npm install

COPY . .

# API base is baked in at build time. deploy.sh / docker-compose pass
# https://api.<domain> (the backend's SITE_URL). Defaults to local dev.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# Stage 2: serve the static build with Nginx (SPA fallback)
FROM nginx:1.25-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
