import { Ajv2020 } from "ajv/dist/2020.js";

const ajv = new Ajv2020({ allErrors: true, strict: false });
export const ok = ajv.compile({ type: "object" })({}) as boolean;
