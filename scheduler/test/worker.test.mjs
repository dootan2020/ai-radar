import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import worker, { dispatchWorkflow } from '../src/index.js';

describe('Cloudflare Worker: ai-radar-scheduler', () => {
  it('proves dispatch request URL, method, headers and body', async () => {
    let callCount = 0;
    let capturedUrl = null;
    let capturedOptions = null;

    const mockFetch = async (url, options) => {
      callCount++;
      capturedUrl = url;
      capturedOptions = options;
      return {
        ok: true,
        status: 204,
        statusText: 'No Content',
        text: async () => ''
      };
    };

    const logs = [];
    const mockLogger = {
      log: (msg) => logs.push({ level: 'log', msg }),
      error: (msg) => logs.push({ level: 'error', msg })
    };

    const env = {
      GITHUB_TOKEN: 'test-token-12345',
      GITHUB_OWNER: 'dootan2020',
      GITHUB_REPO: 'ai-radar',
      GITHUB_WORKFLOW: 'update.yml',
      GITHUB_REF: 'main'
    };

    const result = await dispatchWorkflow(env, {
      fetchFn: mockFetch,
      logger: mockLogger
    });

    // 1. Request URL verification
    assert.equal(callCount, 1, 'fetch must be called exactly once');
    assert.equal(
      capturedUrl,
      'https://api.github.com/repos/dootan2020/ai-radar/actions/workflows/update.yml/dispatches'
    );

    // 2. HTTP Method verification
    assert.equal(capturedOptions.method, 'POST');

    // 3. Headers verification
    assert.equal(capturedOptions.headers['Accept'], 'application/vnd.github+json');
    assert.equal(capturedOptions.headers['Authorization'], 'Bearer test-token-12345');
    assert.equal(capturedOptions.headers['X-GitHub-Api-Version'], '2022-11-28');
    assert.equal(capturedOptions.headers['User-Agent'], 'ai-radar-scheduler');
    assert.equal(capturedOptions.headers['Content-Type'], 'application/json');

    // 4. Request Body verification
    assert.equal(capturedOptions.body, JSON.stringify({ ref: 'main' }));
    const parsedBody = JSON.parse(capturedOptions.body);
    assert.equal(parsedBody.ref, 'main');

    // Result verification
    assert.equal(result.success, true);
    assert.equal(result.status, 204);
  });

  it('proves default repository and workflow if not explicitly in env', async () => {
    let capturedUrl = null;
    const mockFetch = async (url) => {
      capturedUrl = url;
      return { ok: true, status: 204, statusText: 'No Content' };
    };

    const result = await dispatchWorkflow(
      { GITHUB_TOKEN: 'pat-xyz' },
      { fetchFn: mockFetch, logger: { log: () => {}, error: () => {} } }
    );

    assert.equal(result.success, true);
    assert.equal(
      capturedUrl,
      'https://api.github.com/repos/dootan2020/ai-radar/actions/workflows/update.yml/dispatches'
    );
  });

  it('proves missing token logs variable name and makes NO request', async () => {
    let callCount = 0;
    const mockFetch = async () => {
      callCount++;
      return { ok: true, status: 204 };
    };

    const errors = [];
    const mockLogger = {
      log: () => {},
      error: (msg) => errors.push(msg)
    };

    // Environment without GITHUB_TOKEN
    const env = {
      GITHUB_OWNER: 'dootan2020',
      GITHUB_REPO: 'ai-radar'
    };

    const result = await dispatchWorkflow(env, {
      fetchFn: mockFetch,
      logger: mockLogger
    });

    // Proves NO request was made
    assert.equal(callCount, 0, 'No HTTP request should be made when token is missing');

    // Proves variable name was logged
    assert.equal(errors.length, 1, 'Error should be logged exactly once');
    assert.match(
      errors[0],
      /GITHUB_TOKEN/,
      'Log message must explicitly state the missing variable name GITHUB_TOKEN'
    );

    // Proves structured failure return
    assert.equal(result.success, false);
    assert.equal(result.reason, 'missing_token');
    assert.equal(result.variable, 'GITHUB_TOKEN');
  });

  it('proves an HTTP error response is logged once with no retry', async () => {
    let callCount = 0;
    const mockFetch = async () => {
      callCount++;
      return {
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        text: async () => '{"message":"Bad credentials"}'
      };
    };

    const errors = [];
    const mockLogger = {
      log: () => {},
      error: (msg) => errors.push(msg)
    };

    const env = { GITHUB_TOKEN: 'invalid-token' };

    const result = await dispatchWorkflow(env, {
      fetchFn: mockFetch,
      logger: mockLogger
    });

    // Proves called exactly once (no retry burst)
    assert.equal(callCount, 1, 'Worker must not retry when an error occurs');

    // Proves logged once with error details
    assert.equal(errors.length, 1, 'Error should be logged exactly once');
    assert.match(errors[0], /401 Unauthorized/);
    assert.match(errors[0], /Bad credentials/);

    // Proves return value indicates failure
    assert.equal(result.success, false);
    assert.equal(result.status, 401);
  });

  it('proves a 500 server error response is logged once with no retry', async () => {
    let callCount = 0;
    const mockFetch = async () => {
      callCount++;
      return {
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        text: async () => 'GitHub Internal Error'
      };
    };

    const errors = [];
    const mockLogger = {
      log: () => {},
      error: (msg) => errors.push(msg)
    };

    const env = { GITHUB_TOKEN: 'pat-xyz' };

    const result = await dispatchWorkflow(env, {
      fetchFn: mockFetch,
      logger: mockLogger
    });

    assert.equal(callCount, 1, 'No retry attempt on 500 error');
    assert.equal(errors.length, 1);
    assert.match(errors[0], /500 Internal Server Error/);
    assert.equal(result.success, false);
    assert.equal(result.status, 500);
  });

  it('proves network exception is logged once with no retry', async () => {
    let callCount = 0;
    const mockFetch = async () => {
      callCount++;
      throw new Error('Connection refused to api.github.com');
    };

    const errors = [];
    const mockLogger = {
      log: () => {},
      error: (msg) => errors.push(msg)
    };

    const env = { GITHUB_TOKEN: 'valid-pat' };

    const result = await dispatchWorkflow(env, {
      fetchFn: mockFetch,
      logger: mockLogger
    });

    // Proves no retry on thrown network exception
    assert.equal(callCount, 1, 'No retry on network exception');
    assert.equal(errors.length, 1);
    assert.match(errors[0], /Connection refused/);
    assert.equal(result.success, false);
  });

  it('proves worker scheduled event handler calls dispatchWorkflow', async () => {
    let called = false;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      called = true;
      return { ok: true, status: 204, statusText: 'No Content' };
    };

    try {
      const result = await worker.scheduled({}, { GITHUB_TOKEN: 'token-abc' }, {});
      assert.equal(called, true);
      assert.equal(result.success, true);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('proves worker fetch handler endpoints work properly', async () => {
    // 1. Health check endpoint without exposing secret
    const healthReq = new Request('https://worker.local/health');
    const healthRes = await worker.fetch(healthReq, { GITHUB_TOKEN: 'secret-xyz' }, {});
    assert.equal(healthRes.status, 200);
    const healthBody = await healthRes.json();
    assert.equal(healthBody.status, 'ok');
    assert.equal(healthBody.hasToken, true);
    assert.equal(healthBody.repo, 'dootan2020/ai-radar');
    assert.equal(healthBody.workflow, 'update.yml');
    // Crucial check: make sure token value is NOT in the response
    assert.equal(JSON.stringify(healthBody).includes('secret-xyz'), false);

    // 2. 404 endpoint
    const notFoundReq = new Request('https://worker.local/random');
    const notFoundRes = await worker.fetch(notFoundReq, {}, {});
    assert.equal(notFoundRes.status, 404);
  });

  it('proves POST /trigger is gone: 404 and no outgoing request', async () => {
    let called = false;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      called = true;
      return { ok: true, status: 204, statusText: 'No Content' };
    };

    try {
      const req = new Request('https://worker.local/trigger', { method: 'POST' });
      const res = await worker.fetch(req, { GITHUB_TOKEN: 'token-abc' }, {});
      assert.equal(res.status, 404);
      assert.equal(called, false, 'POST /trigger must not reach GitHub');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
