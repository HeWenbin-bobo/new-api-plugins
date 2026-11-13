import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import * as plugin from '../plugin.js';

const fixture = JSON.parse(readFileSync(new URL('../evals/plugin_fixture.json', import.meta.url), 'utf8'));
assert.equal(fixture.cases.length, 14);

for (const fixtureCase of fixture.cases) {
  test(fixtureCase.name, () => {
    const hook = plugin[fixtureCase.hook];
    assert.equal(typeof hook, 'function');
    if (fixtureCase.expectedError) {
      assert.throws(() => hook(...fixtureCase.args), (error) => {
        assert.match(error.message, new RegExp(fixtureCase.expectedError));
        return true;
      });
    } else {
      assert.deepEqual(hook(...fixtureCase.args), fixtureCase.expected);
    }
  });
}
