import { build } from "esbuild";

await build({
  entryPoints: ["web/walletconnect_signing.ts"],
  outfile: "assets/walletconnect-signing.js",
  bundle: true,
  format: "iife",
  platform: "browser",
  target: ["chrome120", "edge120", "safari17"],
  minify: true,
  legalComments: "eof",
  sourcemap: false,
});
