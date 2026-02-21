import test from 'node:test';
import assert from 'node:assert/strict';

const createMatterPath = (firmId) => `/firms/${firmId}/matters`;
const joinUrl = (baseUrl, path) => `${baseUrl.replace(/\/+$/, '')}${path}`;

test('create-matter URL is base + expected path', () => {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL || process.env.VITE_API_BASE_URL || 'https://api.example.com';
  const firmId = 'firm_123';
  const expected = `${baseUrl.replace(/\/+$/, '')}/firms/${firmId}/matters`;

  assert.equal(joinUrl(baseUrl, createMatterPath(firmId)), expected);
});
