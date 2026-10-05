import Ajv2020 from "ajv/dist/2020.js";
import schemaJson from "../../packages/spec/playable-spec.schema.json" with { type: "json" };

const ajv = new Ajv2020({ allErrors: true, strict: false });
const fn = ajv.compile(schemaJson);
export const x = fn({}) as boolean;
export type { ErrorObject } from "ajv";
