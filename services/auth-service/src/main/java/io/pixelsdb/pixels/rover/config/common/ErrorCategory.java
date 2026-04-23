/*
 * Copyright 2024 PixelsDB.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package io.pixelsdb.pixels.rover.config.common;

/**
 * Enumeration of error categories that populates {@code details.category} on failure responses.
 *
 * <p>See {@code backend.md §6.0}. The enum is a closed set (any new value requires a
 * cross-service + frontend synchronized change) and every non-2xx response — with the sole
 * exception of the §6.5 "unknown unhandled exception" safety-net — must carry both
 * {@code details.errorCode} and {@code details.category}.</p>
 *
 * <p>The frontend uses this field as the fall-back layer when no known {@code errorCode}
 * branch applies; without it a newly added backend {@code errorCode} would silently degrade
 * to a generic 5xx banner (see {@code backend.md §6.3.2}).</p>
 */
public enum ErrorCategory
{
    /** User-supplied input is invalid (format / required / length / etc.). */
    USER_INPUT,

    /** Authentication / session / CSRF failure. */
    AUTH,

    /** Rate limit exceeded / quota exhausted. */
    RATE_LIMIT,

    /** An upstream dependency (DB / LLM / introspect / ...) is transiently unavailable. */
    UPSTREAM,

    /** Server-side unknown error / access-plane fault. */
    INTERNAL
}
