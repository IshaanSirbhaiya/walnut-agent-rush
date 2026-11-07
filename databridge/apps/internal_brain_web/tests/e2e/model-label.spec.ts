import { expect, test } from '@playwright/test';
import { answerSource, modelLabelKey, modelTipKey } from '../../components/user/answerText';
import { translate } from '../../lib/i18n';
import { userMessages } from '../../lib/i18n/user';
import type { ModelInfo } from '../../lib/types';

// Story 1 fix #2: the answer footer tells the TRUE reason a quoted answer was served, from the API's
// `model.reason_code` (databridge_ib/narrate.py REASON_CODES). Pure helpers: no page, no server.

const D = { provider: 'deterministic', model: 'extractive-v1' };
const CASES: { name: string; m: ModelInfo; src: string; en: RegExp; zh: RegExp }[] = [
  { name: 'model rejected for evidence', m: { ...D, fallback_used: true, reason_code: 'model_rejected_evidence' }, src: 'rejected', en: /evidence check/, zh: /证据检查/ },
  { name: 'model timed out or unavailable', m: { ...D, fallback_used: true, reason_code: 'model_unavailable' }, src: 'unavailable', en: /unavailable or too slow/, zh: /不可用或响应过慢/ },
  { name: 'approved script quoted (D-43)', m: { ...D, fallback_used: false, reason_code: 'quoted_approved_script' }, src: 'script', en: /Approved wording/, zh: /经批准/ },
  { name: 'no model configured', m: { ...D, fallback_used: false }, src: 'offline', en: /no AI model on/, zh: /未启用 AI 模型/ },
];
/** A label or tooltip must never show the provider key or the model id it was given. */
const names = (m: ModelInfo) => (['deterministic', 'model'].includes(m.provider) ? [m.model] : [m.provider, m.model]); // 'model' is the generic key
const leaks = (s: string, m: ModelInfo) => names(m).some((n) => s.toLowerCase().includes(n.toLowerCase()));

for (const c of CASES) {
  test(`model label: ${c.name}`, () => {
    expect(answerSource(c.m)).toBe(c.src);
    const key = modelLabelKey(c.m);
    const en = translate(userMessages, 'en', key);
    const zh = translate(userMessages, 'zh', key);
    expect(en).toMatch(c.en);
    expect(zh).toMatch(c.zh);
    const tip = modelTipKey(c.m);
    expect(tip).not.toBeNull();
    for (const s of [en, zh, translate(userMessages, 'en', tip!), translate(userMessages, 'zh', tip!)]) {
      expect(leaks(s, c.m)).toBe(false);
    }
    // only a second model writing after the first failed may say "the first model did not answer"
    expect(tip).not.toBe('answer.model.fallbackTip');
  });
}

test('model label: the rejected and timed-out cases never share a label or a tooltip', () => {
  const [rej, una] = CASES;
  expect(modelLabelKey(rej.m)).not.toBe(modelLabelKey(una.m));
  expect(modelTipKey(rej.m)).not.toBe(modelTipKey(una.m));
  expect(translate(userMessages, 'en', modelTipKey(rej.m)!)).not.toMatch(/in time|timed out|unavailable/);
});

test('model label: a model-written answer says AI once; a second model gets the fallback tip', () => {
  // Any configured model, whatever its name (the API reports the configured name, or "AI model").
  for (const ai of [
    { provider: 'model', model: 'acme-llm-7b', fallback_used: false },
    { provider: 'model', model: 'AI model', fallback_used: false },
    { provider: 'chat-completions', model: 'example-large-2', fallback_used: false },
  ] as ModelInfo[]) {
    expect(answerSource(ai)).toBe('ai');
    expect(translate(userMessages, 'en', modelLabelKey(ai))).toBe('AI model');
    expect(translate(userMessages, 'zh', modelLabelKey(ai))).toBe('AI 模型');
    if (ai.model !== 'AI model') expect(leaks(translate(userMessages, 'en', modelTipKey(ai)), ai)).toBe(false);
  }
  const ai: ModelInfo = { provider: 'model', model: 'acme-llm-7b', fallback_used: false };
  const en = translate(userMessages, 'en', modelLabelKey(ai));
  expect(leaks(en, ai)).toBe(false);
  expect(translate(userMessages, 'en', 'answer.aiNote')).toMatch(/AI-generated/);
  expect(en).not.toMatch(/AI-generated/);
  expect(modelTipKey({ ...ai, fallback_used: true })).toBe('answer.model.fallbackTip');
});
