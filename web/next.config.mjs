/** @type {import('next').NextConfig} */
const nextConfig = {
  // Self-contained server for the Docker image (web/Dockerfile)
  output: "standalone",
  reactStrictMode: true,
};
export default nextConfig;
