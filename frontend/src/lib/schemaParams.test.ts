import { describe, expect, it } from 'vitest';
import { buildParams, paramsToStrings, propType } from './schemaParams';

const schema = {
  properties: {
    min: { anyOf: [{ type: 'number' }, { type: 'null' }] },
    inclusive: { type: 'boolean', default: true },
    values: { type: 'array' },
    regex: { type: 'string' },
    operator: { enum: ['lt', 'gt'] },
  },
};

describe('schema-driven parameters', () => {
  it('resolves nullable and enum property types', () => {
    expect(propType(schema.properties.min)).toEqual({ type: 'number', format: undefined, nullable: true });
    expect(propType(schema.properties.operator).type).toBe('enum');
  });

  it('converts form strings into typed parameters and omits blanks', () => {
    expect(buildParams(schema, { min: '0.5', inclusive: 'false', values: 'paid, refunded ,', regex: '^a', operator: '' })).toEqual({
      min: 0.5,
      inclusive: false,
      values: ['paid', 'refunded'],
      regex: '^a',
    });
  });

  it('round-trips stored parameters back into form strings', () => {
    expect(paramsToStrings({ values: ['a', 'b'], min: 1, max: null })).toEqual({ values: 'a, b', min: '1' });
  });
});
