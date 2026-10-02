/** Settings for the Mastra app, read from environment variables (the repo-root .env is loaded by the runner). */

import { existsSync, mkdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

/** Only these settings are read from the repo-root .env. Mastra never needs your API keys, so it never loads them. */
const WANTED = ['STYLIST_API_URL', 'EVAL_USERS', 'EVAL_USER_EMAIL', 'EVAL_USER_PASSWORD', 'OTEL_TRACES_ENDPOINT', 'OTEL_SERVICE_NAME', 'MASTRA_DATA_DIR']

function loadWantedFromDotenv(): void {
  for (let dir = process.cwd(), i = 0; i < 4; dir = resolve(dir, '..'), i++) {
    const file = resolve(dir, '.env')
    if (!existsSync(file)) continue
    for (const line of readFileSync(file, 'utf-8').split(/\r?\n/)) {
      const m = /^([A-Z_]+)=(.*)$/.exec(line.trim())
      if (m && WANTED.includes(m[1]) && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^"|"$/g, '')
    }
    return
  }
}
loadWantedFromDotenv()

const env = process.env

/** Where Mastra keeps its own data: traces, scores, datasets, and the audit chain. An absolute path, so
 *  Studio and a script that run from different folders still read the SAME database. */
/** The folder holding this app's package.json, found by walking up from where we are running. Studio (`mastra dev`)
 *  runs the code from a build folder inside the project, so the working directory alone is not reliable. */
function projectRoot(): string {
  for (let dir = process.cwd(), i = 0; i < 6; dir = resolve(dir, '..'), i++) {
    const pkg = resolve(dir, 'package.json')
    if (existsSync(pkg) && /"name":\s*"mastra-app"/.test(readFileSync(pkg, 'utf-8'))) return dir
  }
  return process.cwd()
}

export const dataDir = resolve(env.MASTRA_DATA_DIR || resolve(projectRoot(), '.data'))
mkdirSync(dataDir, { recursive: true })

export const config = {
  apiUrl: env.STYLIST_API_URL || 'http://localhost:8000',
  /** Shopper accounts the workflow signs in as (created on first use). Cases are spread across them so no one
   *  account trips the API's per-user rate limit, which we deliberately do not weaken for tests. */
  evalUsers: Number(env.EVAL_USERS || 4),
  evalEmail: (i: number) => (env.EVAL_USER_EMAIL ? env.EVAL_USER_EMAIL.replace('@', `+${i}@`) : `eval-bot-${i}@example.com`),
  evalPassword: env.EVAL_USER_PASSWORD || 'a long passphrase used only for evals',
  mastraDbUrl: pathToFileURL(resolve(dataDir, 'mastra.db')).href,
  auditDbUrl: pathToFileURL(resolve(dataDir, 'audit.db')).href,
  /** If set, traces are also sent here (OTLP over HTTP), e.g. a local Jaeger on http://localhost:4318/v1/traces */
  otlpEndpoint: env.OTEL_TRACES_ENDPOINT || undefined,
  serviceName: env.OTEL_SERVICE_NAME || 'stylist-mastra',
}
