# Dev image: Vite dev server with HMR. Source bind-mounted at /app by docker
# compose; a named volume masks /app/node_modules so the linux deps in the
# container don't get clobbered by a darwin host node_modules.
FROM node:22-alpine AS dev

WORKDIR /app

# Install deps first so the layer is cached when only source changes
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# --host 0.0.0.0 so the dev server is reachable from the host network
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
