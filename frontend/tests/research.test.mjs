import assert from "node:assert/strict";
import { test } from "node:test";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Compile the actual components without starting a browser or dev server.
const require = createRequire(import.meta.url);
function compile(path, imports = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2020,
    },
  });
  const module = { exports: {} };
  const resolve = (name) => imports[name] ?? require(name);
  new Function("require", "module", "exports", outputText)(resolve, module, module.exports);
  return module.exports;
}
const utilities = compile("../src/lib/research.ts");
const { safeResearchUrl } = utilities;
const { ResearchReport } = compile("../src/components/ResearchReport.tsx", {
  "../lib/research": utilities,
});
const render = (text, citations = []) =>
  renderToStaticMarkup(createElement(ResearchReport, { text, citations }));

test("renders Unicode-aware inline citations without losing surrounding text", () => {
  const text = "📊 Market outlook [1] and risk [2].";
  const chars = Array.from(text);
  const first = chars.join("").indexOf("[1]") - 1;
  const second = chars.join("").indexOf("[2]") - 1;
  const output = render(text, [
    { url: "https://www.sec.gov", title: "SEC", start_index: first, end_index: first + 3 },
    {
      url: "https://www.treasury.gov",
      title: "Treasury",
      start_index: second,
      end_index: second + 3,
    },
  ]);
  assert.match(output, /📊 Market outlook /);
  assert.match(output, /href="https:\/\/www.sec.gov\/"/);
  assert.match(output, /href="https:\/\/www.treasury.gov\/"/);
  assert.match(output, /and risk/);
  assert.match(output, /rel="noopener noreferrer"/);
});

test("renders comparison tables, lists, headings and emphasis", () => {
  const output = render(
    "## Key figures\n| Fund | Exposure |\n| --- | --- |\n| SPY | **Large cap** |\n| VTI | Broad market |\n\n- First risk\n- Second risk",
  );
  assert.match(output, /<h3>Key figures<\/h3>/);
  assert.match(output, /<table>/);
  assert.match(output, /<strong>Large cap<\/strong>/);
  assert.equal((output.match(/<li>/g) || []).length, 2);
});

test("untrusted report HTML and unsafe citations cannot execute", () => {
  const output = render(
    "<script>alert(1)</script>\n[Bad](javascript:alert(1))\n<img src=x onerror=alert(1)>",
    [{ url: "javascript:alert(1)", title: "Bad", start_index: 0, end_index: 8 }],
  );
  assert.doesNotMatch(output, /<script|<img|href="javascript:/);
  assert.match(output, /&lt;script&gt;/);
  assert.equal(safeResearchUrl("data:text/html,test"), null);
  assert.equal(safeResearchUrl("https://user:pass@example.com"), null);
});

test("citation spans outside the report do not corrupt it", () => {
  assert.equal(
    render("An intact report.", [
      { url: "https://www.sec.gov", title: "SEC", start_index: 99, end_index: 104 },
    ]),
    '<div class="research-report"><p>An intact report.</p></div>',
  );
});

test("submitting research sends the chosen provider and idempotency key", async () => {
  const calls = [];
  const api = compile("../src/api/research.ts", {
    "../lib/apiClient": {
      apiClient: {
        post: async (url, body) => {
          calls.push({ url, body });
          return { data: { id: "run", provider: body.provider } };
        },
      },
    },
  });
  const result = await api.submitMessage("session", "Compare funds", "request-id", "anthropic");
  assert.equal(result.provider, "anthropic");
  assert.deepEqual(calls, [
    {
      url: "/research/sessions/session/messages",
      body: {
        prompt: "Compare funds",
        provider: "anthropic",
        request_id: "request-id",
      },
    },
  ]);
});

const { InvestmentAnalysisView } = compile("../src/components/InvestmentAnalysis.tsx");
test("investment evidence renders accessible charts, benchmark metrics and limitations", () => {
  const snapshot = {
    symbol: "AAPL",
    observed_at: "2026-10-08",
    warnings: ["Cash earns zero."],
    analysis: {
      price: 110,
      sma50: 105,
      sma200: 100,
      distance_sma50: 0.0476,
      distance_sma200: 0.1,
      sma50_change_20_sessions: 0.02,
      sma200_change_20_sessions: null,
      last_crossover: null,
      trend: [
        { date: "2025-01-01", price: 100, sma50: null, sma200: null },
        { date: "2026-10-08", price: 110, sma50: 105, sma200: 100 },
      ],
      backtests: [
        {
          strategy: "buy_hold",
          period: "full",
          start: "2025-01-01",
          end: "2026-10-08",
          total_return: 0.1,
          annualized_return: 0.05,
          max_drawdown: -0.2,
          annualized_volatility: 0.15,
          trades: 1,
          time_invested: 0.99,
          curve: [
            { date: "2025-01-01", equity: 100, drawdown: 0 },
            { date: "2026-10-08", equity: 110, drawdown: -0.05 },
          ],
        },
      ],
      assumptions: ["Next-session execution."],
    },
  };
  const output = renderToStaticMarkup(createElement(InvestmentAnalysisView, { snapshot }));
  assert.equal((output.match(/role="img"/g) || []).length, 3);
  assert.match(output, /Buy &amp; hold/);
  assert.match(output, /-20.0%/);
  assert.match(output, /Unavailable/);
  assert.match(output, /Next-session execution/);
  assert.match(output, /Cash earns zero/);
  assert.match(output, /tabindex="0"/);
  assert.equal(
    renderToStaticMarkup(createElement(InvestmentAnalysisView, { snapshot: { symbol: "OLD" } })),
    "",
  );
});
