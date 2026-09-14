import { readdir, readFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import assert from 'node:assert/strict';
import test from 'node:test';

test('public install packages contain no account profiles, client defaults or symlinks', async () => {
  const root = resolve(import.meta.dirname, '../plugins');
  async function scan(dir) {
    for (const e of await readdir(dir, {withFileTypes: true})) {
      const p = join(dir, e.name);
      assert.equal(e.isSymbolicLink(), false, `symlink: ${p}`);
      assert.ok(!['private-profiles', 'sub-accounts', 'node_modules', '.env', 'ACCOUNT.md', 'config.local.json'].includes(e.name), `private/development path: ${p}`);
      if (e.isDirectory()) await scan(p);
      else {
        const text = await readFile(p, 'utf8');
        assert.doesNotMatch(text, /embarkearthworks|horizonprodental|Horizon Pro|Embark Jobs|BEGIN [A-Z ]*PRIVATE KEY|gh[pousr]_[A-Za-z0-9_]{30,}/i, `client/credential marker: ${p}`);
      }
    }
  }
  await scan(root);
});
