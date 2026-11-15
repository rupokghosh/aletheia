import os from "node:os";
import path from "node:path";
import { existsSync } from "node:fs";
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(96);
Config.setCodec("h264");
Config.setCrf(18);
Config.setPixelFormat("yuv420p");
Config.setConcurrency(6);
Config.setOverwriteOutput(true);

// Use a headless browser that is already on this machine (Playwright's) when there is one, instead of
// downloading another.
const local = path.join(os.homedir(), "Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell");
if (existsSync(local)) Config.setBrowserExecutable(local);
