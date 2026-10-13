/** Helpers for rendering forms from the backend's JSON-schema parameter definitions. */

export type SchemaProp = {
  type?: string;
  anyOf?: { type?: string; format?: string }[];
  enum?: string[];
  default?: unknown;
  description?: string;
  format?: string;
  exclusiveMinimum?: number;
  minimum?: number;
  maximum?: number;
};

export type ParamsSchema = { properties?: Record<string, SchemaProp> };

export function propType(prop: SchemaProp): { type: string; format?: string; nullable: boolean } {
  if (prop.enum) return { type: 'enum', nullable: false };
  if (prop.type) return { type: prop.type, format: prop.format, nullable: false };
  const nonNull = prop.anyOf?.find((p) => p.type !== 'null');
  return { type: nonNull?.type ?? 'string', format: nonNull?.format, nullable: true };
}

/** Convert form strings into the typed parameter object the API validates. Empty fields are omitted. */
export function buildParams(schema: ParamsSchema, values: Record<string, string>): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    const { type } = propType(prop);
    const value = values[key];
    if (value === undefined || value === '') continue;
    if (type === 'number' || type === 'integer') params[key] = Number(value);
    else if (type === 'boolean') params[key] = value === 'true';
    else if (type === 'array') params[key] = value.split(',').map((v) => v.trim()).filter(Boolean);
    else params[key] = value;
  }
  return params;
}

export function paramsToStrings(params: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    out[key] = Array.isArray(value) ? value.join(', ') : String(value);
  }
  return out;
}
