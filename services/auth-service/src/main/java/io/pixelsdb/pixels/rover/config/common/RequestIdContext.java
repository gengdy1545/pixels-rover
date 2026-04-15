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

public final class RequestIdContext
{
    private static final ThreadLocal<String> REQUEST_ID_HOLDER = new ThreadLocal<>();

    private RequestIdContext()
    {
    }

    public static void set(String requestId)
    {
        REQUEST_ID_HOLDER.set(requestId);
    }

    public static String get()
    {
        return REQUEST_ID_HOLDER.get();
    }

    public static void clear()
    {
        REQUEST_ID_HOLDER.remove();
    }
}
