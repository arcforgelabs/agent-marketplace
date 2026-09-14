import { describe, it, expect, vi } from 'vitest';
import { createGhlClient } from './client.js';
import { resolveConfig } from './config.js';
import { contacts, tasks } from './operations.js';

describe('release behavior', () => {
  it.each([429, 500, 503])('never automatically repeats writes after HTTP %s', async (status) => {
    const f = vi.fn(async () => new Response('{}', {status}));
    await expect(createGhlClient({token:'synthetic', fetchImpl:f}).request('POST', '/conversations/messages', {body:{message:'test'}})).rejects.toThrow();
    expect(f).toHaveBeenCalledTimes(1);
  });
  it('does not repeat writes after ambiguous network failure or leak transport errors', async () => {
    const f = vi.fn(async () => {throw new Error('synthetic-credential');});
    await expect(createGhlClient({token:'synthetic-credential', fetchImpl:f}).request('POST', '/contacts/upsert')).rejects.toThrow('verify the outcome');
    expect(f).toHaveBeenCalledTimes(1);
  });
  it('passes abort and rejects redirects', async () => {
    const controller = new AbortController();
    const f = vi.fn(async (_url, options) => {
      expect(options.redirect).toBe('error');
      expect(options.signal).toBeInstanceOf(AbortSignal);
      return new Response('{}');
    });
    const client = createGhlClient({token:'synthetic', fetchImpl:f, signal:controller.signal});
    await client.request('GET', '/contacts/');
    controller.abort();
    await expect(client.request('GET', '/contacts/')).rejects.toThrow();
    expect(f).toHaveBeenCalledTimes(1);
  });
  it('uses email/phone queries and rejects identifier path injection', async () => {
    const request = vi.fn(async () => ({}));
    const config = resolveConfig({locationId:'location_test', privateIntegrationToken:'synthetic'});
    await contacts({request}, config, {action:'search', email:'alex@example.com'});
    expect(request.mock.calls[0][2].query.query).toBe('alex@example.com');
    await expect(contacts({request}, config, {action:'get', contactId:'../other'})).rejects.toThrow('Invalid contactId');
    await tasks({request},config,{action:'complete',contactId:'contact_test',taskId:'task_test'});
    expect(request.mock.calls[1][2].body).toEqual({completed:true});
  });
  it('has no regional default and validates account/timezone configuration', () => {
    expect(resolveConfig({locationId:'test',privateIntegrationToken:'synthetic'}).timezone).toBeUndefined();
    expect(() => resolveConfig({locationId:'../other',privateIntegrationToken:'synthetic'})).toThrow();
    expect(() => resolveConfig({locationId:'test',privateIntegrationToken:'synthetic',timezone:'not-a-zone'})).toThrow();
  });
});
