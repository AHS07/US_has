# Build stage
FROM node:22-alpine AS build

WORKDIR /app

COPY healthflow-ui/package.json healthflow-ui/package-lock.json* healthflow-ui/pnpm-lock.yaml* ./
RUN npm install

COPY healthflow-ui/ ./
RUN npm run build

# Production stage
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
