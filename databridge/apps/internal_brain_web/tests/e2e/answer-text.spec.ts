import { expect, test } from '@playwright/test';
import { gatherTags } from '../../components/user/answerText';
import { PERSONAS, personaById } from '../../lib/personas';

// No browser or server: `npx playwright test -c tests/e2e/pure.config.ts`.

test.describe('gatherTags: each chip stays on its own sentence', () => {
  test('the quoted answer form, tag after the full stop (the default, no-model path)', () => {
    const quoted =
      'Any purchase above SGD 10,000 needs three written quotes. [C1] Spend above SGD 5,000 also needs the Head of Finance. [C2]';
    expect(gatherTags(quoted)).toBe(
      'Any purchase above SGD 10,000 needs three written quotes [C1]. Spend above SGD 5,000 also needs the Head of Finance [C2].',
    );
  });

  test('the model form, tag before the full stop, is unchanged', () => {
    const model = 'Three quotes are needed [C1]. The Head of Finance approves [C2].';
    expect(gatherTags(model)).toBe(model);
  });

  test('several tags on one sentence gather, and no tag is left alone at the end', () => {
    expect(gatherTags('One thing. [C1] [C2] Another. [C3]')).toBe('One thing [C1,C2]. Another [C3].');
  });

  test('a decimal or version number does not split a sentence', () => {
    expect(gatherTags('The fee is 1.5 percent. [C1]')).toBe('The fee is 1.5 percent [C1].');
  });

  test('tags inside a sentence still gather at its end', () => {
    expect(gatherTags('Quotes [C1] and approval [C2] are needed.')).toBe('Quotes and approval are needed [C1,C2].');
  });
});

test.describe('Alex, the procurement persona', () => {
  const alex = personaById('admin.it')!;

  test('the header reads as a person with a job, matching the greeting', () => {
    expect(alex.fullName.split(' ')[0]).toBe(alex.name);
    expect(alex.role).toBe('IT admin');
  });

  test('the simulator he operates is still said out loud at sign-in', () => {
    expect(alex.note).toMatch(/simulator/i);
  });

  test('the first four starters (all the home page shows) include the procurement question', () => {
    expect(alex.suggestions.slice(0, 4).join(' ')).toMatch(/12 laptops/);
  });

  test('no other persona is called a simulator', () => {
    expect(PERSONAS.filter((p) => /simulator/i.test(p.role))).toEqual([]);
  });
});
