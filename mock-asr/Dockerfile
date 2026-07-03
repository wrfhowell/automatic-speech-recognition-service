FROM node:20-alpine

# socat: asr-server.js binds 127.0.0.1:3000 (Fastify default host) which is
# unreachable from outside the container, and the server file is provided
# vendor code we do not modify. socat re-exposes it on 0.0.0.0:3001.
RUN apk add --no-cache socat

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY asr-server.js mock-transcripts.js ./

EXPOSE 3001
CMD ["sh", "-c", "node asr-server.js & socat TCP-LISTEN:3001,fork,reuseaddr TCP:127.0.0.1:3000"]
