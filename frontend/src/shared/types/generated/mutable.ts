/**
 * Mutable projection of a readonly-deep type.
 *
 * Why this exists
 * ---------------
 * ``openapi-typescript`` is invoked with ``--immutable`` (see
 * ``frontend/package.json`` ``gen:types`` script) so that every generated
 * property is ``readonly`` and every array is ``readonly T[]``. That is
 * the correct default for a wire-shape: you should never mutate a
 * response payload in place.
 *
 * BUT: Ant Design tables, React-Query's ``select`` callbacks, and several
 * store reducers all consume ``T[]`` rather than ``readonly T[]`` in their
 * own published types. Forcing every caller to wrap generated wire shapes
 * in ``[...arr]`` or cast away ``readonly`` would defeat the ergonomic
 * point of shipping types at all.
 *
 * This helper flips the recursive ``readonly`` off so the hand-written
 * DTO facade files (``analysis.d.ts``, ``conversation.d.ts``, ``sse.d.ts``)
 * can export caller-friendly mutable aliases while the underlying
 * ``components['schemas']`` remains the SSOT. Renaming or removing a
 * backend field still breaks ``tsc`` because the alias directly
 * references the generated schema — only the depth of ``readonly`` is
 * stripped, the structural shape is not.
 *
 * Intentionally narrow: we only peel ``readonly`` from arrays and object
 * properties. Tuples, ``Map``, ``Set``, ``Promise``, and class instances
 * are left alone.
 */
export type Mutable<T> = T extends readonly (infer U)[]
  ? Mutable<U>[]
  : T extends object
    ? { -readonly [K in keyof T]: Mutable<T[K]> }
    : T;
