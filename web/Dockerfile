FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json index.html server.ts ./
COPY src ./src
COPY fixtures ./fixtures
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist
COPY server.ts ./
USER node
EXPOSE 8080
CMD ["node", "--experimental-strip-types", "server.ts"]
