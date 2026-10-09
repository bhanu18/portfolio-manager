import assert from "node:assert/strict";
import { test } from "node:test";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(path, imports) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (name) => imports[name] ?? require(name),
    module,
    module.exports,
  );
  return module.exports;
}

function fixture(trades = [], lookup = (ids) => ids.map((id) => ({ id, symbol: `SYM${id}` }))) {
  const requests = [];
  const apiClient = {
    async get(url) {
      requests.push({ method: "GET", url });
      assert.equal(url, "/trades/in-group/7", "No per-asset GET requests should remain");
      return { data: trades };
    },
    async post(url, body) {
      requests.push({ method: "POST", url, body });
      assert.equal(url, "/assets/batch");
      return { data: await lookup(body.ids) };
    },
  };
  const assets = compile("../src/api/assets.ts", { "../lib/apiClient": { apiClient } });
  const api = compile("../src/api/trades.ts", {
    "../lib/apiClient": { apiClient },
    "./assets": assets,
  });
  return { requests, assets, api };
}
const trade = (id, assetId, symbol) => ({
  id,
  asset_id: assetId,
  symbol,
  trade_type: "buy",
  trade_date: "2026-10-08",
  quantity: 1,
  price_per_unit: 100,
  currency: "USD",
  group_id: 7,
});

test("many trades resolve all unique asset IDs in one batch", async () => {
  const { api, requests } = fixture([
    trade(1, 11),
    trade(2, 12),
    trade(3, 11),
    trade(4, 13, "KNOWN"),
  ]);
  const result = await api.listTradesInGroup(7);
  assert.equal(requests.length, 2);
  assert.deepEqual(requests[1], { method: "POST", url: "/assets/batch", body: { ids: [11, 12] } });
  assert.deepEqual(
    result.map((row) => row.symbol),
    ["SYM11", "SYM12", "SYM11", "KNOWN"],
  );
});

test("embedded symbols and empty trade lists need no asset request", async () => {
  for (const trades of [[], [trade(1, 11, "AAPL")]]) {
    const { api, requests } = fixture(trades);
    assert.equal((await api.listTradesInGroup(7)).length, trades.length);
    assert.equal(requests.length, 1);
  }
});

test("missing assets preserve transactions and already known symbols", async () => {
  const { api } = fixture([trade(1, 11), trade(2, 12), trade(3, 13, "KNOWN")], () => [
    { id: 11, symbol: "AAPL" },
  ]);
  const rows = await api.listTradesInGroup(7);
  assert.deepEqual(
    rows.map((row) => row.symbol),
    ["AAPL", undefined, "KNOWN"],
  );
  assert.deepEqual(
    rows.map((row) => row.id),
    [1, 2, 3],
  );
});

test("batch failures leave transactions visible", async () => {
  const { api } = fixture([trade(1, 11), trade(2, 12, "MSFT")], () => {
    throw new Error("Unavailable");
  });
  assert.deepEqual(
    (await api.listTradesInGroup(7)).map((row) => row.symbol),
    [undefined, "MSFT"],
  );
});

test("large portfolios use bounded batches, with deduplication and no invalid IDs", async () => {
  const { assets, requests } = fixture();
  const ids = Array.from({ length: 501 }, (_, i) => i + 1);
  const result = await assets.getAssetsByIds([...ids, 1, 0, -1, 1.5]);
  assert.equal(result.length, 501);
  assert.deepEqual(
    requests.map((request) => request.body.ids.length),
    [500, 1],
  );
  assert.equal(result[500].id, 501);
  await assets.getAssetsByIds([]);
  assert.equal(requests.length, 2);
});
