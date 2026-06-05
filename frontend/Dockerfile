# ---------------------------------------------------------------------------
# Dev: Vite dev server with HMR.
# Source bind-mounted at /app by docker compose; a named volume masks
# /app/node_modules so the linux deps in the container don't get clobbered
# by a darwin host node_modules.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS dev

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---------------------------------------------------------------------------
# Builder: compile the Vite production bundle
# ---------------------------------------------------------------------------
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# VITE_API_URL defaults to relative /api so the SPA proxies through the
# same origin in production; override at build time for cross-origin setups.
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# ---------------------------------------------------------------------------
# Prod: serve the static bundle with a tiny nginx image
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS prod

# Remove default nginx config and replace with SPA-friendly config
RUN rm /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

# nginx config: serve index.html for all non-asset routes (React Router)
RUN printf 'server {\n\
    listen 80;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
\n\
    # API proxy — point to backend (override NGINX_BACKEND at runtime)\n\
    location /api/ {\n\
        proxy_pass http://backend:8000;\n\
        proxy_set_header Host $host;\n\
        proxy_set_header X-Real-IP $remote_addr;\n\
    }\n\
\n\
    # React Router — all non-file requests serve index.html\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/app.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
