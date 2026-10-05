/**
 * Cloudflare Worker: ai-radar-scheduler
 *
 * Triggers GitHub Actions workflows via GitHub REST API workflow_dispatch:
 * - .github/workflows/update.yml (every 20 minutes)
 * - .github/workflows/shadow-collector.yml (once an hour)
 * Operates on Cloudflare Free plan via Cron Triggers.
 * GitHub token is read strictly from Worker environment secret (GITHUB_TOKEN).
 */

export const CRON_UPDATE = '*/20 * * * *';
export const CRON_SHADOW = '5 * * * *';

const DEFAULT_OWNER = 'dootan2020';
const DEFAULT_REPO = 'ai-radar';
const DEFAULT_WORKFLOW = 'update.yml';
const DEFAULT_SHADOW_WORKFLOW = 'shadow-collector.yml';
const DEFAULT_REF = 'main';

/**
 * Dispatches GitHub Actions workflow.
 *
 * @param {object} env - Worker environment bindings
 * @param {object} [options] - Options for testing / dependency injection
 * @param {Function} [options.fetchFn=fetch] - Fetch implementation
 * @param {object} [options.logger=console] - Logger implementation
 * @param {string} [options.workflow] - Workflow file to dispatch (overrides env.GITHUB_WORKFLOW)
 * @returns {Promise<{success: boolean, status?: number, statusText?: string, error?: string, reason?: string, variable?: string}>}
 */
export async function dispatchWorkflow(env = {}, { fetchFn = fetch, logger = console, workflow = undefined } = {}) {
  const token = env.GITHUB_TOKEN;
  if (!token) {
    logger.error('Missing required environment secret: GITHUB_TOKEN');
    return {
      success: false,
      reason: 'missing_token',
      variable: 'GITHUB_TOKEN'
    };
  }

  const owner = env.GITHUB_OWNER || DEFAULT_OWNER;
  const repo = env.GITHUB_REPO || DEFAULT_REPO;
  const targetWorkflow = workflow || env.GITHUB_WORKFLOW || DEFAULT_WORKFLOW;
  const ref = env.GITHUB_REF || DEFAULT_REF;

  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${targetWorkflow}/dispatches`;

  const headers = {
    'Accept': 'application/vnd.github+json',
    'Authorization': `Bearer ${token}`,
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'ai-radar-scheduler',
    'Content-Type': 'application/json'
  };

  const body = JSON.stringify({ ref });

  try {
    // Exactly one single request; no retry burst on failure
    const response = await fetchFn(url, {
      method: 'POST',
      headers,
      body
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => '');
      logger.error(
        `GitHub API dispatch failed with status ${response.status} ${response.statusText}: ${errorText}`
      );
      return {
        success: false,
        status: response.status,
        statusText: response.statusText,
        error: errorText
      };
    }

    logger.log(
      `GitHub workflow dispatch succeeded for ${owner}/${repo} (${targetWorkflow} @ ${ref}) with status ${response.status}`
    );
    return {
      success: true,
      status: response.status
    };
  } catch (err) {
    const errorMsg = err?.message || String(err);
    logger.error(`Network error during GitHub API dispatch: ${errorMsg}`);
    return {
      success: false,
      error: errorMsg
    };
  }
}

export default {
  /**
   * Cron Trigger handler
   */
  async scheduled(event = {}, env = {}, ctx = {}) {
    const logger = ctx?.logger || console;
    const cron = event?.cron;

    let targetWorkflow;
    if (cron === CRON_UPDATE) {
      targetWorkflow = env.GITHUB_WORKFLOW || DEFAULT_WORKFLOW;
    } else if (cron === CRON_SHADOW) {
      targetWorkflow = env.GITHUB_SHADOW_WORKFLOW || DEFAULT_SHADOW_WORKFLOW;
    } else {
      logger.error(
        `Unknown cron trigger: "${cron}". Expected "${CRON_UPDATE}" or "${CRON_SHADOW}". No workflow dispatched.`
      );
      return {
        success: false,
        reason: 'unknown_cron',
        cron
      };
    }

    return dispatchWorkflow(env, {
      fetchFn: ctx?.fetchFn || fetch,
      logger,
      workflow: targetWorkflow
    });
  },

  /**
   * HTTP handler for health checks only (no route can dispatch the workflow)
   */
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/' || url.pathname === '/health') {
      return new Response(
        JSON.stringify({
          status: 'ok',
          service: 'ai-radar-scheduler',
          hasToken: Boolean(env.GITHUB_TOKEN),
          workflow: env.GITHUB_WORKFLOW || DEFAULT_WORKFLOW,
          shadowWorkflow: env.GITHUB_SHADOW_WORKFLOW || DEFAULT_SHADOW_WORKFLOW,
          repo: `${env.GITHUB_OWNER || DEFAULT_OWNER}/${env.GITHUB_REPO || DEFAULT_REPO}`,
          ref: env.GITHUB_REF || DEFAULT_REF
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json; charset=utf-8' }
        }
      );
    }

    return new Response('Not Found', { status: 404 });
  }
};
