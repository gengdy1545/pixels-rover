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
package io.pixelsdb.pixels.rover.constant;

public final class ErrorCode
{
    private ErrorCode()
    {
    }

    public static final int INVALID_ARGUMENT = 40000;
    public static final int AUTHENTICATION_REQUIRED = 40100;
    public static final int INVALID_CREDENTIALS = 40101;
    public static final int INVALID_TOKEN = 40102;
    public static final int INVALID_TOKEN_TYPE = 40103;
    public static final int ACCESS_DENIED = 40300;
    public static final int RESOURCE_NOT_FOUND = 40400;
    public static final int RESOURCE_CONFLICT = 40900;
    public static final int DEPENDENCY_ERROR = 50200;
    public static final int INTERNAL_ERROR = 50000;
}
