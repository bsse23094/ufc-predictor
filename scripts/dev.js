/**
 * Concurrently starts both FastAPI Backend (port 8000) and Next.js Web Frontend (port 3000).
 * Provides cross-platform unified development orchestration.
 */

const { spawn } = require("child_process");
const path = require("path");

const rootDir = path.resolve(__dirname, "..");

console.log("\x1b[36m%s\x1b[0m", "[dev] Starting UFC Predictor Unified Development Environment...");
console.log("\x1b[36m%s\x1b[0m", "[dev] Backend: http://127.0.0.1:8000");
console.log("\x1b[36m%s\x1b[0m", "[dev] Frontend: http://localhost:3000");

// 1. Start FastAPI Backend
const apiCmd = "uv";
const apiArgs = [
  "run",
  "--project",
  "apps/api",
  "python",
  "-m",
  "uvicorn",
  "ufc_api.main:create_app",
  "--factory",
  "--reload",
  "--host",
  "127.0.0.1",
  "--port",
  "8000",
];

const apiProcess = spawn(apiCmd, apiArgs, {
  cwd: rootDir,
  shell: true,
  stdio: ["inherit", "pipe", "pipe"],
  env: { ...process.env, PYTHONUNBUFFERED: "1" },
});

apiProcess.stdout.on("data", (data) => {
  const lines = data.toString().trim().split("\n");
  for (const line of lines) {
    if (line.trim()) console.log("\x1b[35m[api]\x1b[0m " + line);
  }
});

apiProcess.stderr.on("data", (data) => {
  const lines = data.toString().trim().split("\n");
  for (const line of lines) {
    if (line.trim()) console.error("\x1b[35m[api]\x1b[0m " + line);
  }
});

// 2. Start Next.js Frontend
const webCmd = "corepack";
const webArgs = ["pnpm", "--filter", "@ufc-predictor/web", "dev"];

const webProcess = spawn(webCmd, webArgs, {
  cwd: rootDir,
  shell: true,
  stdio: ["inherit", "pipe", "pipe"],
  env: { ...process.env, FORCE_COLOR: "1" },
});

webProcess.stdout.on("data", (data) => {
  const lines = data.toString().trim().split("\n");
  for (const line of lines) {
    if (line.trim()) console.log("\x1b[34m[web]\x1b[0m " + line);
  }
});

webProcess.stderr.on("data", (data) => {
  const lines = data.toString().trim().split("\n");
  for (const line of lines) {
    if (line.trim()) console.error("\x1b[34m[web]\x1b[0m " + line);
  }
});

function cleanup() {
  console.log("\x1b[36m%s\x1b[0m", "\n[dev] Shutting down development processes...");
  try {
    if (process.platform === "win32") {
      if (apiProcess.pid) spawn("taskkill", ["/pid", apiProcess.pid, "/f", "/t"]);
      if (webProcess.pid) spawn("taskkill", ["/pid", webProcess.pid, "/f", "/t"]);
    } else {
      if (apiProcess.pid) apiProcess.kill("SIGTERM");
      if (webProcess.pid) webProcess.kill("SIGTERM");
    }
  } catch (err) {
    // Ignore cleanup errors
  }
  process.exit(0);
}

process.on("SIGINT", cleanup);
process.on("SIGTERM", cleanup);
process.on("exit", cleanup);
