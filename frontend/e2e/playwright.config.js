const { defineConfig, devices } = require("/e2e-deps/node_modules/@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  outputDir: "./test-results",
  timeout: 90000,
  workers: 1,
  retries: 0,
  use: {
    baseURL: process.env.BASE_URL,
    actionTimeout: 15000,
    screenshot: "only-on-failure",
    locale: "pt-BR",
    timezoneId: "America/Sao_Paulo",
  },
  projects: [
    { name: "pc", use: { ...devices["Desktop Chrome"] } },
    { name: "android", use: { ...devices["Pixel 7"] } },
    { name: "iphone", use: { ...devices["iPhone 14"] } },
  ],
});
