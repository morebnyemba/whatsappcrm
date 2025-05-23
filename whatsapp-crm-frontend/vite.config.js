// whatsappcrm-frontend/vite.config.js
import path from "path"
import tailwindcss from "@tailwindcss/vite" // Assuming you're using this plugin for Tailwind
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: { // <<< ADD THIS SERVER CONFIGURATION
    // This allows the Vite dev server to be accessed via these hostnames.
    // Your Vite dev server typically runs on localhost:5173 (or another port).
    // The error "Blocked request. This host ("popular-real-squirrel.ngrok-free.app") is not allowed."
    // means that a request *to your Vite dev server* had this ngrok URL as its Host header.
    // This is unusual if 'popular-real-squirrel.ngrok-free.app' is the ngrok URL for your *backend*.
    //
    // However, if you are specifically tunneling your Vite frontend dev server
    // and 'popular-real-squirrel.ngrok-free.app' IS the public URL for your Vite frontend,
    // then this setting is correct.
    //
    // If 'popular-real-squirrel.ngrok-free.app' is for your Django backend,
    // and you access your frontend via http://localhost:5173, then requests from your
    // frontend to the backend ngrok URL should not cause Vite to block anything.
    // This setting only affects requests *received by* the Vite dev server.
    allowedHosts: [
      'localhost',
      '127.0.0.1',
      // Add the specific ngrok hostname that Vite is complaining about.
      'popular-real-squirrel.ngrok-free.app', 
    ],
    // You can also specify the port if it's not the default 5173
    // port: 5173, 
  }
})
