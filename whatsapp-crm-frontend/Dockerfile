# Stage 1: Build the React app
FROM node:20-alpine AS build

WORKDIR /app

# Copy package.json and package-lock.json (or yarn.lock)
COPY package.json ./
# If you use yarn, replace the next two lines accordingly
COPY package-lock.json ./
RUN npm install

# Copy the rest of the frontend application code
COPY . .

# Build the application
RUN npm run build

# Stage 2: Serve the built app with Nginx
FROM nginx:1.25-alpine

# Copy the build output from the 'build' stage
COPY --from=build /app/dist /usr/share/nginx/html

# (Optional) Copy a custom Nginx configuration if needed
# COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80 (default for Nginx)
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]