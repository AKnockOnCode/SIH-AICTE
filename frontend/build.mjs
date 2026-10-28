// AgniDrishti frontend build: esbuild bundles the React/TypeScript app; Tailwind CSS v4 is compiled
// through its JavaScript API (no PostCSS or CLI needed). Output goes to dist/, which the backend
// serves on the same port as the API (http://localhost:8000).
//
//   node build.mjs           production build (minified, content-hashed assets)
//   node build.mjs --watch   rebuild on change (unminified, stable file names)

import * as esbuild from "esbuild";
import { compile } from "tailwindcss";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const src = path.join(root, "src");
const dist = path.join(root, "dist");
const assets = path.join(dist, "assets");
const watch = process.argv.includes("--watch");
const require = createRequire(import.meta.url);
const tailwindDir = path.dirname(require.resolve("tailwindcss/package.json"));

async function walk(dir) {
  const out = [];
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await walk(p)));
    else if (/\.(tsx?|html|css)$/.test(entry.name)) out.push(p);
  }
  return out;
}

// Candidate extraction (what Tailwind's native scanner would do): every class-like token in the
// sources. Over-inclusion is harmless; Tailwind ignores tokens that are not utilities.
async function candidates() {
  const set = new Set();
  const files = [...(await walk(src)), path.join(root, "index.html")];
  for (const file of files) {
    const text = await fs.readFile(file, "utf8");
    for (const m of text.matchAll(/[^<>"'`\s]*[^<>"'`\s:]/g)) {
      const token = m[0].replace(/^[{(,;]+|[},;)]+$/g, "");
      if (token && token.length < 120) set.add(token);
    }
  }
  return set;
}

async function buildCss() {
  const input = await fs.readFile(path.join(src, "app.css"), "utf8");
  const compiler = await compile(input, {
    base: src,
    loadStylesheet: async (id, base) => {
      let file;
      if (id === "tailwindcss") file = path.join(tailwindDir, "index.css");
      else if (id.startsWith("tailwindcss/")) file = path.join(tailwindDir, id.slice("tailwindcss/".length));
      else file = path.resolve(base, id);
      if (!file.endsWith(".css")) file += ".css";
      return { path: file, base: path.dirname(file), content: await fs.readFile(file, "utf8") };
    },
    loadModule: async (id) => {
      throw new Error(`Tailwind plugin/config modules are not used in this project (${id})`);
    },
  });
  const css = compiler.build([...(await candidates())]);
  const { code } = await esbuild.transform(css, { loader: "css", minify: !watch, target: ["chrome111", "firefox113", "safari16.4"] });
  return code;
}

const hash = (text) => createHash("sha256").update(text).digest("hex").slice(0, 10);

async function writeOutputs(jsText, cssText) {
  await fs.mkdir(assets, { recursive: true });
  const jsName = watch ? "app.js" : `app-${hash(jsText)}.js`;
  const cssName = watch ? "app.css" : `app-${hash(cssText)}.css`;
  if (!watch) {
    for (const f of await fs.readdir(assets)) if (/^app(-[0-9a-f]+)?\.(js|css)$/.test(f)) await fs.rm(path.join(assets, f));
  }
  await fs.writeFile(path.join(assets, jsName), jsText);
  await fs.writeFile(path.join(assets, cssName), cssText);
  const html = (await fs.readFile(path.join(root, "index.html"), "utf8"))
    .replace("%APP_CSS%", `/assets/${cssName}`)
    .replace("%APP_JS%", `/assets/${jsName}`);
  await fs.writeFile(path.join(dist, "index.html"), html);
  for (const f of await fs.readdir(path.join(root, "public")).catch(() => [])) {
    await fs.copyFile(path.join(root, "public", f), path.join(dist, f));
  }
  return { jsName, cssName };
}

const options = {
  entryPoints: [path.join(src, "main.tsx")],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["chrome111", "firefox113", "safari16.4"],
  jsx: "automatic",
  write: false,
  outdir: assets,
  sourcemap: watch ? "inline" : false,
  minify: !watch,
  legalComments: "none",
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  logLevel: "warning",
};

if (watch) {
  const ctx = await esbuild.context({
    ...options,
    plugins: [{
      name: "samanvay-output",
      setup(build) {
        build.onEnd(async (result) => {
          if (result.errors.length) return;
          const js = result.outputFiles.find((f) => f.path.endsWith(".js"));
          await writeOutputs(js.text, await buildCss());
          console.log(`[${new Date().toLocaleTimeString()}] rebuilt dist/`);
        });
      },
    }],
  });
  await ctx.watch();
  console.log("Watching frontend/src for changes. UI is served by the backend at http://localhost:8000");
} else {
  const started = Date.now();
  const result = await esbuild.build(options);
  const js = result.outputFiles.find((f) => f.path.endsWith(".js"));
  const css = await buildCss();
  const { jsName, cssName } = await writeOutputs(js.text, css);
  const kb = (n) => `${(n / 1024).toFixed(0)} kB`;
  console.log(`dist/assets/${jsName} ${kb(js.text.length)} | dist/assets/${cssName} ${kb(css.length)} | ${Date.now() - started} ms`);
}
