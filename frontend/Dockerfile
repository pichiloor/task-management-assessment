# Build: TypeScript check and Vite production bundle.
FROM node:24.14.1-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Runtime: nginx serves the bundle and proxies /api to the backend, so the
# browser talks to one origin (no CORS).
FROM nginx:1.30.1-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
