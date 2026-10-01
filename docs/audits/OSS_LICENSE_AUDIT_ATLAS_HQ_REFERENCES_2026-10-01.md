# OSS Licence Audit — Atlas HQ Visual-Layer Reference Repositories

- Date: 2026-10-01
- Mode: RESEARCH MODE (CLAUDE.md). No code from these repos was executed, installed, or copied. Repo content was treated as untrusted data.
- Scope: licence / asset / dependency audit of four repositories proposed as *reference only* (ideas, possibly small fragments) for a future Atlas HQ visual layer.
- Roadmap note: Atlas HQ is UI work; per CLAUDE.md it never delays Core. This audit authorizes nothing; it is input for a later Adopt/Adapt/Reject decision.

## Method and limits

- FACT sources: `https://raw.githubusercontent.com/<owner>/<repo>/HEAD/<file>` (default branch via `HEAD`). Fetched with curl through the session proxy on 2026-10-01.
- `api.github.com` and `github.com` HTML pages were **blocked** in this session (403 / "GitHub access not enabled for this session"). Consequently the following were NOT verifiable for any repo: GitHub-detected SPDX metadata, full file tree, asset folder contents, commit history / last commit date, default-branch name.
- Dependency licences below are INFERENCE from well-known upstream licensing of those packages; they were NOT fetched per package in this session.

## Summary table

| Repo | LICENSE (FACT) | Copyright holder (FACT) | Third-party assets | Copyleft / NC deps seen | Last commit | Verdict |
|---|---|---|---|---|---|---|
| avalla/ai-office | MIT | Andrea Valla (2026) | None mentioned in README; UNKNOWN — requires verification | None in root package.json | UNKNOWN | Adopt-ideas-only (low relevance to visuals) |
| fedevgonzalez/pixel-office | MIT | Pablo De Lucca (2025) + Federico Gonzalez (2026) | YES — paid Donarg tileset (not in repo) + characters based on JIK-A-4 "Metro City" | None seen | UNKNOWN | Adapt-code-with-notice (code only); assets: Reject |
| WW-AI-Lab/openclaw-office | MIT | "OpenClaw" (2026) | Not mentioned; SVG avatars generated in code (README) | None seen (mermaid/recharts etc. permissive, inference) | UNKNOWN (package version `2026.6.11`) | Adapt-code-with-notice |
| OneByJorah/VirtOffice | MIT | Jhonattan L. Jimenez (OneByJorah / JorahOne Networks) (2026) | Not mentioned; Three.js r128 from CDN | None (stdlib server) | UNKNOWN | Adapt-code-with-notice |

---

## 1. avalla/ai-office

**FACT**
- LICENSE: MIT License text, `Copyright (c) 2026 Andrea Valla`. Source: https://raw.githubusercontent.com/avalla/ai-office/HEAD/LICENSE
- README line 5: "Licensed under the [MIT License](LICENSE). Copyright (c) 2026 Andrea Valla." Source: https://raw.githubusercontent.com/avalla/ai-office/HEAD/README.md
- package.json: `"license": "MIT"`, `"private": true`, Bun workspace (`apps/*`, `packages/*`). Runtime dependency: `zod ^4.0.0`. devDependencies: `@eslint/js`, `@types/bun`, `eslint`, `prettier`, `typescript`, `typescript-eslint`, `vitest`. Source: https://raw.githubusercontent.com/avalla/ai-office/HEAD/package.json
- README describes a CLI/daemon "office" for agent orchestration (model routing, budgets, read models, launchd/systemd service management); no visual asset section found by keyword search (credit/asset/tileset/sprite/font/sound).

**UNKNOWN — requires verification**: workspace sub-package (`apps/*`, `packages/*`) dependencies and licences; presence of any image/font/sound assets; last commit date.

**INFERENCE**: zod, eslint, prettier, typescript, vitest are MIT/Apache-2.0/BSD-style (no copyleft). This repo is primarily a headless orchestration tool, so it has little direct value for a visual layer; its value is conceptual (governed agent office, budgets, approved organizational model).

**Verdict: Adopt-ideas-only.** If any fragment is ever copied: retain MIT notice; verify the sub-package's own licence field.

## 2. fedevgonzalez/pixel-office

**FACT**
- LICENSE: MIT with two copyright lines: `Copyright (c) 2025 Pablo De Lucca — Pixel Agents (https://github.com/pablodelucca/pixel-agents)` and `Copyright (c) 2026 Federico Gonzalez — Pixel Office`, plus a statement that it is a fork of Pixel Agents and the original notice is preserved. Source: https://raw.githubusercontent.com/fedevgonzalez/pixel-office/HEAD/LICENSE
- README "Office Assets": tileset is "Office Interior Tileset (16x16) by Donarg ($2 on itch.io)" (https://donarg.itch.io/officetileset); "Characters are based on Metro City by JIK-A-4" (https://jik-a-4.itch.io/metrocity-free-topdown-character-pack). "The tileset is not included in this repo"; users must purchase it and run `pnpm import-tileset`. Source: https://raw.githubusercontent.com/fedevgonzalez/pixel-office/HEAD/README.md
- README also lists "Sound notifications" (audio chime) — source/licence of the sound file not stated.
- Root package.json: `"license": "MIT"`; dependency `ws ^8.19.0`; devDependencies include `@anthropic-ai/sdk`, `esbuild`, `eslint`, `gifenc`, `npm-run-all`, `playwright`, `pngjs`, `tsx`, `typescript`, `typescript-eslint`. Source: https://raw.githubusercontent.com/fedevgonzalez/pixel-office/HEAD/package.json
- webview-ui/package.json: dependencies `react`, `react-dom` (^19.2); devDependencies Vite/ESLint/TypeScript tooling. Source: https://raw.githubusercontent.com/fedevgonzalez/pixel-office/HEAD/webview-ui/package.json
- Upstream Pixel Agents README: bundled characters, pets, furniture live under `webview-ui/public/assets/`; "6 diverse characters ... based on ... JIK-A-4, Metro City". Upstream licence badge points to `pixel-agents-hq/pixel-agents` (repo apparently moved). Source: https://raw.githubusercontent.com/pablodelucca/pixel-agents/HEAD/README.md

**UNKNOWN — requires verification**: exact contents of `webview-ui/public/assets/` in pixel-office (whether Metro City-derived character sprites are committed); the licence terms of the Metro City pack and of the Donarg tileset (itch.io pages were not fetched); whether the MIT licence is intended to cover the derived sprites (the LICENSE says "Software", it does not mention art); source of the notification sound; last commit date.

**INFERENCE**: The MIT grant reliably covers the code only. Character sprites derived from a third-party itch.io pack may carry that pack's own terms (attribution, redistribution limits) which MIT cannot override. The Donarg tileset is a paid asset and must not be redistributed by Atlas. ws/react/esbuild/pngjs/gifenc are permissive (MIT/BSD/ISC-family); no copyleft observed.

**Verdict: Adapt-code-with-notice for code; Reject for all art/sound assets.** Any copied code fragment must carry BOTH copyright lines (De Lucca and Gonzalez) plus the MIT permission notice. Do not copy any PNG/sprite/tileset/sound; Atlas would need its own or separately licensed assets.

## 3. WW-AI-Lab/openclaw-office

**FACT**
- LICENSE: MIT, `Copyright (c) 2026 OpenClaw`. Source: https://raw.githubusercontent.com/WW-AI-Lab/openclaw-office/HEAD/LICENSE
- package.json: name `@ww-ai-lab/openclaw-office`, version `2026.6.11`, `"license": "MIT"`. dependencies: i18next, i18next-browser-languagedetector, immer, js-yaml, lucide-react, mermaid, react, react-dom, react-i18next, react-markdown, react-router-dom, react-textarea-autosize, recharts, remark-gfm, zustand. devDependencies: @tailwindcss/vite, testing-library, jsdom, tailwindcss, typescript, vite, vitest, fake-indexeddb, types. Source: https://raw.githubusercontent.com/WW-AI-Lab/openclaw-office/HEAD/package.json
- README (Chinese): 2D office floor plan "SVG-rendered isometric office scene"; agent avatars "deterministically generated SVG from agentId"; README ends with `[MIT](./LICENSE)`. `./assets/*.png` referenced are screenshots. No third-party asset credits found. Source: https://raw.githubusercontent.com/WW-AI-Lab/openclaw-office/HEAD/README.md

**UNKNOWN — requires verification**: legal identity of "OpenClaw" as copyright holder vs. the `WW-AI-Lab` org; whether any bundled fonts/icons beyond lucide-react exist; `bin/` scripts' dependencies; last commit date.

**INFERENCE**: All listed dependencies are commonly MIT (react, zustand, immer, recharts, mermaid, i18next, js-yaml) or ISC (lucide-react, which also includes MIT-licensed Feather-derived icons). No copyleft observed. Code-generated SVG art lowers asset-licence risk relative to the pixel-art repos.

**Verdict: Adapt-code-with-notice.** Retain `Copyright (c) 2026 OpenClaw` + MIT notice on any fragment; if lucide icons are used, include lucide's ISC/MIT notices.

## 4. OneByJorah/VirtOffice

**FACT**
- LICENSE: MIT, `Copyright (c) 2026 Jhonattan L. Jimenez (OneByJorah / JorahOne Networks)`. Source: https://raw.githubusercontent.com/OneByJorah/VirtOffice/HEAD/LICENSE
- No package.json (404). requirements.txt contains only comments: "Minimal deps placeholder; server uses only stdlib." Source: https://raw.githubusercontent.com/OneByJorah/VirtOffice/HEAD/requirements.txt
- README: Python stdlib HTTP server + Three.js floor plan, SSE/polling/webhooks; "Tech Stack: Python (stdlib HTTP server) · Three.js · Server-Sent Events · Docker · Docker Compose"; "MIT — see LICENSE". Source: https://raw.githubusercontent.com/OneByJorah/VirtOffice/HEAD/README.md
- public/office.html loads `https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js` (only external URL found besides the SVG namespace). Source: https://raw.githubusercontent.com/OneByJorah/VirtOffice/HEAD/public/office.html

**UNKNOWN — requires verification**: whether 3D furniture/characters are procedural geometry (README suggests so, not verified line-by-line) or include external models/textures/fonts; licence of `docs/assets/banner.svg`; `scripts/hermes_bridge.py` imports; last commit date.

**INFERENCE**: Three.js is MIT. Zero third-party server dependencies means minimal transitive licence risk. Three.js r128 is an old release (2021); copying code tied to r128 APIs would need adaptation to a current Three.js.

**Verdict: Adapt-code-with-notice.** Retain the Jimenez MIT notice on fragments; if Three.js is bundled, include its MIT notice.

---

## Obligations for commercial use (all four are MIT)

FACT (from the MIT text in each LICENSE): commercial use, modification, and distribution are permitted on condition that "the above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software"; no warranty.

RECOMMENDATION:
1. Keep a `THIRD_PARTY_NOTICES` (or equivalent) entry per source repo with the exact copyright line(s) and the MIT text whenever a "substantial portion" is copied; mark copied code with a header comment pointing to source repo + commit SHA.
2. Ideas, layouts, and concepts (not code expression) need no notice, but write Atlas implementations independently.
3. MIT does not grant trademark rights; do not reuse names "Pixel Office", "Pixel Agents", "OpenClaw", "VirtOffice", "AI Office" or logos.
4. MIT on code does not cover third-party art; treat every image/sprite/model/sound/font as separately licensed until proven otherwise.

## Before copying ANY fragment (checklist)

1. Pin the exact commit SHA (not verifiable this session) and re-read LICENSE at that SHA.
2. Confirm the fragment is original to the repo (not vendored from another project with different terms; check file headers and git blame).
3. For pixel-office: confirm the fragment is not asset data or a manifest describing the paid Donarg tileset / Metro City sprites.
4. Check transitive dependencies the fragment requires (run a licence scanner on a lockfile in an isolated environment, per CLAUDE.md Discover→License→Security→Quality→Compatibility→Test→Adopt/Adapt/Reject).
5. Security review of the fragment (untrusted code; no `eval`, no network beacons, no install scripts).
6. Record the decision in Atlas governance (What/Why/Where/Dependencies/Risk/Cost/Alternative/Decision) before adoption.

## Deferred items

- Re-run this audit with GitHub API / web access enabled to obtain: GitHub SPDX detection, full asset trees, last-commit dates, and itch.io licence terms for Donarg and JIK-A-4 Metro City.
